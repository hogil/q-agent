"""Typed local bridge to the synthetic model worker in its own environment."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


def _worker_error(operation, message):
    if operation == 'actions':
        return ValueError('ACTION_OUTCOME_UNKNOWN: the worker response was lost; '
                          'check action-status with the original request before further actions')
    return ValueError(message)


class ModelLabService:
    def __init__(self, settings):
        self.options = settings.data.get('model_lab', {})
        if settings.data['environment'] != 'demo' or not self.options.get('enabled'):
            raise ValueError('synthetic model lab is not enabled')
        self.process = None; self.errors = None; self.lock = threading.RLock()
        self.progress_state = {'running': False, 'events': []}
        atexit.register(self.close)

    def close(self):
        with self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill.exe', '/PID', str(self.process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
                    else: self.process.terminate()
                    try: self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
                self.process = None
            if self.errors is not None: self.errors.close(); self.errors = None

    def _start(self):
        options = self.options
        if not Path(options['source_root']).is_dir() or not all(Path(options[key]).is_file() for key in ('python', 'base_config', 'overlay')):
            raise ValueError('configured synthetic worker files are missing')
        log = Path(options['stderr_file']); log.parent.mkdir(parents=True, exist_ok=True)
        self.errors = log.open('a', encoding='utf-8')
        env = dict(os.environ, PYTHONPATH=str(Path(options['source_root']) / 'src'),
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        self.process = subprocess.Popen([options['python'], '-m', 'qmodels.platform_runtime',
            '--config', options['base_config'], '--overlay', options['overlay']],
            cwd=options['source_root'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.errors, text=True, encoding='utf-8', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def request(self, operation, body):
        if operation not in ('catalog', 'analyze', 'actions', 'action-status', 'report', 'dispatch-check'):
            raise ValueError('unknown model lab operation')
        if operation == 'action-status':
            return self._action_status(body)
        with self.lock:
            if operation == 'analyze': self.progress_state = {'running': True, 'events': [], 'case_id': body.get('case_id') if isinstance(body, dict) else None}
            if self.process is None or self.process.poll() is not None:
                self.close(); self._start()
            try:
                self.process.stdin.write(json.dumps({'operation': operation, 'body': body}, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
            except OSError:
                self.close()
                raise _worker_error(operation, 'synthetic worker communication failed') from None
            responses = queue.Queue(maxsize=1)
            process = self.process
            def read_response():
                try:
                    while True:
                        line = process.stdout.readline()
                        if not line: responses.put(''); break
                        value = json.loads(line)
                        if 'event' in value:
                            self.progress_state['events'] = [*self.progress_state['events'], value['event']][-32:]
                        else: responses.put(line); break
                except (OSError, ValueError): responses.put('')
                finally:
                    if operation == 'analyze': self.progress_state['running'] = False
            thread = threading.Thread(target=read_response, daemon=True); thread.start()
            try: line = responses.get(timeout=self.options['timeout_seconds'])
            except queue.Empty:
                self.close(); raise _worker_error(operation, 'synthetic worker timed out; outcome unavailable') from None
            if not line:
                self.close(); raise _worker_error(operation, 'synthetic worker stopped; inspect its configured log')
            result = json.loads(line)
            if result.get('ok') is not True: raise ValueError(result.get('error', 'worker rejected request'))
            return result['result']

    def _action_status(self, body):
        # A lost response may follow a committed transaction. Never retry the write.
        # This separate read-only CLI does not start models or require run-memory.
        options = self.options
        env = dict(os.environ, PYTHONPATH=str(Path(options['source_root']) / 'src'),
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        try:
            response = subprocess.run([options['python'], '-m', 'qmodels.action_receipt_lookup_v1',
                '--config', options['base_config'], '--overlay', options['overlay']],
                cwd=options['source_root'], env=env, input=json.dumps({'operation': 'action-status', 'body': body}),
                capture_output=True, text=True, encoding='utf-8', timeout=min(options['timeout_seconds'], 10),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise ValueError('action status lookup timed out; original action outcome remains unknown') from None
        if response.returncode != 0:
            raise ValueError('action status lookup unavailable; original action outcome remains unknown')
        try:
            value = json.loads(response.stdout)
        except ValueError:
            raise ValueError('invalid action status response; original action outcome remains unknown') from None
        if not isinstance(value, dict) or value.get('ok') is not True:
            raise ValueError(value.get('error', 'action status lookup failed') if isinstance(value, dict) else 'action status lookup failed')
        return value['result']

    def progress(self):
        return {**self.progress_state, 'events': list(self.progress_state['events'])}
