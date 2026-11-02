"""Opt-in local research jobs. Business evidence belongs to the lab worker only."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager


class Conflict(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ref(path):
    p = Path(path).resolve()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(p), 'sha256': h.hexdigest()}


def checked(pin):
    if not isinstance(pin, dict) or set(pin) != {'path', 'sha256'} or ref(pin['path']) != pin:
        raise ValueError('expected source hash mismatch')
    return pin['path']


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def validate_body(body):
    if not isinstance(body, dict) or set(body) != {'client_request_id', 'case_token', 'question', 'selectors'}:
        raise ValueError('only explicit case, original question, selectors and request UUID are allowed')
    if not isinstance(body['client_request_id'], str):
        raise ValueError('canonical request UUID required')
    if str(uuid.UUID(body['client_request_id'])) != body['client_request_id']:
        raise ValueError('canonical request UUID required')
    if not isinstance(body['question'], str) or not 1 <= len(body['question']) <= 1200:
        raise ValueError('question must contain 1–1200 characters; no truncation')
    if not isinstance(body['case_token'], str) or not 1 <= len(body['case_token']) <= 128:
        raise ValueError('explicit catalog case required')
    selectors = body['selectors']
    names = {'equipment_candidate', 'trend_step', 'legend', 'metro_item', 'measure_channel',
             'schema_term', 'history_chunk_id', 'query_image_id', 'process_steps', 'process_pass',
             'metro_steps', 'metro_items'}
    if not isinstance(selectors, dict) or set(selectors) - names:
        raise ValueError('unknown selector')
    for key, value in selectors.items():
        if key in {'process_steps', 'metro_steps', 'metro_items'}:
            if (not isinstance(value, list) or not 1 <= len(value) <= 24
                    or any(not isinstance(v, str) or not 1 <= len(v) <= 80 for v in value)
                    or len(set(value)) != len(value)):
                raise ValueError('bounded unique selector list required')
        elif key == 'equipment_candidate':
            if type(value) is not int or value < 0:
                raise ValueError('nonnegative equipment candidate required')
        elif key == 'process_pass':
            if not (type(value) is int and value in (1, 2) or type(value) is str and value == 'all'):
                raise ValueError('explicit process pass required')
        elif not isinstance(value, str) or not 1 <= len(value) <= 160:
            raise ValueError('bounded explicit selector required')
    return body


class JobStore:
    """A separate operational DB; never a business Tool or source authority."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, room TEXT NOT NULL, client TEXT NOT NULL, intent TEXT NOT NULL,
                payload TEXT NOT NULL, grant_id TEXT NOT NULL, expires REAL NOT NULL,
                created REAL NOT NULL, state TEXT NOT NULL, result TEXT,
                UNIQUE(room,client));
              CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, job, payload):
        db.execute('INSERT INTO events(job,payload) VALUES (?,?)', (job, json.dumps(payload, ensure_ascii=False)))

    @staticmethod
    def row(row):
        if row is None:
            return None
        return {'job_id': row['id'], 'client_request_id': row['client'], 'room_id': row['room'],
                'state': row['state'], 'request': json.loads(row['payload']),
                'result': json.loads(row['result']) if row['result'] else None,
                'created': row['created'], 'expires': row['expires'], 'grant_id': row['grant_id']}

    def enqueue(self, room, client, request, grant_id, quota, expires):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM jobs WHERE room=? AND client=?', (room, client)).fetchone()
            intent = digest(request)
            if previous:
                if previous['intent'] != intent:
                    raise Conflict('idempotency key already binds a different request')
                return self.row(previous)
            if time.time() >= expires:
                raise Conflict('startup grant expired')
            if db.execute('SELECT count(*) FROM jobs WHERE grant_id=?', (grant_id,)).fetchone()[0] >= quota:
                raise Conflict('startup grant quota exhausted')
            active = ('QUEUED', 'WAITING_GPU', 'RUNNING')
            if db.execute('SELECT 1 FROM jobs WHERE room=? AND state IN (?,?,?)', (room, *active)).fetchone():
                raise Conflict('room already has an active research job')
            if db.execute("SELECT count(*) FROM jobs WHERE state IN ('QUEUED','WAITING_GPU')").fetchone()[0] >= 2:
                raise Conflict('research queue is full')
            job = 'WBR-' + str(uuid.uuid4())
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,NULL)',
                       (job, room, client, intent, json.dumps(request, ensure_ascii=False), grant_id,
                        expires, time.time(), 'QUEUED'))
            self.event(db, job, {'event': 'queued', 'job_id': job})
            return self.row(db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone())

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('RUNNING','WAITING_GPU')").fetchone():
                return None
            row = db.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='WAITING_GPU' WHERE id=? AND state='QUEUED'", (row['id'],))
            return self.row(db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())

    def finish(self, job, state, result):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,result=? WHERE id=?', (state, json.dumps(result, ensure_ascii=False), job))
            self.event(db, job, {'event': 'state', 'state': state, 'result': result})

    def get(self, room, job, after=0):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND room=?', (job, room)).fetchone()
            if not row:
                raise ValueError('research job not found in this room')
            value = self.row(row)
            value['events'] = [{'seq': r['seq'], **json.loads(r['payload'])} for r in db.execute(
                'SELECT seq,payload FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 200', (job, after))]
            return value

    def latest(self, room):
        with self.connect() as db:
            row = db.execute('SELECT id FROM jobs WHERE room=? ORDER BY created DESC LIMIT 1', (room,)).fetchone()
        return self.get(room, row['id']) if row else None


def from_options(options):
    if not options or options.get('enabled') is False:
        return None
    return ResearchService(options)


def admit_research_site_overlay(options, engineering_path, platform_path):
    """Metadata compatibility only; the service still requires its independent startup grant."""
    engineering_path = Path(engineering_path).resolve()
    if engineering_path.name in ('demo.yaml', 'engineering-demo.yaml'):
        return {'legacy': True}
    if not isinstance(options, dict) or options.get('enabled') is not True:
        raise ValueError('an explicit enabled research bridge is required for this site overlay')
    profile = read(checked(options['profile']))
    if profile.get('enabled') is not True or profile.get('final_source_approved') is not True:
        raise ValueError('research site profile has not received source approval')
    freeze = read(checked(profile['bridge_source_freeze']))
    if freeze.get('status') != 'approved' or freeze.get('approved_by') != 'ROOT':
        raise ValueError('ROOT-approved research source freeze required')
    binding = profile.get('research_site_overlay_binding')
    names = {'engineering_overlay', 'platform_overlay', 'registry', 'lock',
             'source_engineering_overlay', 'source_platform_overlay', 'source_registry', 'source_lock',
             'smoke_manifest', 'smoke_correction'}
    if not isinstance(binding, dict) or set(binding) != names:
        raise ValueError('exact research site-overlay descriptor binding required')
    for pin in binding.values():
        if pin not in freeze['files']:
            raise ValueError('research site descriptor is not in the approved source closure')
        checked(pin)
    if (engineering_path != Path(binding['engineering_overlay']['path']).resolve()
            or platform_path is None
            or Path(platform_path).resolve() != Path(binding['platform_overlay']['path']).resolve()):
        raise ValueError('requested research engineering/platform paths differ from source approval')
    smoke = read(binding['smoke_manifest']['path'])
    correction = read(binding['smoke_correction']['path'])
    def descriptor(value):
        return {key: value[key] for key in ('path', 'sha256')}
    source_names = {'engineering_overlay': 'research_engineering_overlay',
                    'platform_overlay': 'research_platform_overlay', 'registry': 'research_registry',
                    'lock': 'research_lock', 'source_engineering_overlay': 'source_engineering_overlay',
                    'source_platform_overlay': 'source_platform_overlay', 'source_registry': 'default_registry',
                    'source_lock': 'default_release_lock'}
    if any(descriptor(smoke['source_pins'][source]) != binding[name] for name, source in source_names.items()):
        raise ValueError('research smoke manifest does not bind these exact sources')
    if (descriptor(correction['prior_record']) != binding['smoke_manifest']
            or correction['corrected_judge_compile'].get('exit_code') != 0
            or correction['corrected_judge_compile'].get('status') != 'PASS'):
        raise ValueError('corrected source-only Judge smoke evidence required')
    import yaml
    for name in ('engineering', 'platform'):
        current_pin, original_pin = binding[name + '_overlay'], binding['source_' + name + '_overlay']
        current = yaml.safe_load(Path(current_pin['path']).read_text(encoding='utf-8'))
        original = yaml.safe_load(Path(original_pin['path']).read_text(encoding='utf-8'))
        if current.get('environment') != 'demo':
            raise ValueError('research site must remain a demo environment')
        for field, target in (('registry_file', 'registry'), ('skill_lock_file', 'lock')):
            value = current.get('paths', {}).get(field)
            if not isinstance(value, str) or (Path(current_pin['path']).parent / value).resolve() != Path(binding[target]['path']).resolve():
                raise ValueError('research registry/lock path differs from the bound descriptor')
        # All original site settings remain equal except the two explicitly declared source paths.
        import copy
        left, right = copy.deepcopy(current), copy.deepcopy(original)
        for data in (left, right):
            for field in ('registry_file', 'skill_lock_file'):
                data.get('paths', {}).pop(field, None)
        if left != right:
            raise ValueError('research site changed settings beyond registry/lock paths')
    registry, source_registry = read(binding['registry']['path']), read(binding['source_registry']['path'])
    release = smoke['research_release']
    if (registry.get('release') != release or correction['corrected_judge_compile'].get('release') != release
            or {k: v for k, v in registry.items() if k != 'release'} != {k: v for k, v in source_registry.items() if k != 'release'}):
        raise ValueError('research registry must preserve original roles/topics and change only release label')
    lock, source_lock = read(binding['lock']['path']), read(binding['source_lock']['path'])
    if lock.get('release') != release or set(lock.get('files', {})) != set(source_lock.get('files', {})):
        raise ValueError('research lock must preserve the original declared file set')
    return {'legacy': False, 'scope': 'source compatibility only; not startup authority',
            'profile': options['profile'], 'research_release': release, 'binding': binding}


class ResearchService:
    def __init__(self, options):
        self.options = options
        self.profile_path = checked(options['profile'])
        self.profile = read(self.profile_path)
        p = self.profile
        if p.get('enabled') is not True or p.get('final_source_approved') is not True:
            raise ValueError('research source profile is inactive')
        self.source = read(checked(p['bridge_source_freeze']))
        for pin in self.source['files']:
            checked(pin)
        grant_pin = {'path': p['startup_grant']['path'], 'sha256': options['startup_grant_expected_SHA256']}
        self.grant_pin = grant_pin
        self.grant = read(checked(grant_pin))
        self.admit_startup()
        self.stop_event = threading.Event()
        self.store = JobStore(p['job_DB'])
        self.thread = None
        # A previous wrapper may still own the GPU. Reconciliation is operator-only.
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('RUNNING','WAITING_GPU')").fetchone():
                raise ValueError('prior research worker requires explicit ROOT reconciliation')

    def admit_startup(self):
        p, g = self.profile, self.grant
        checked(self.grant_pin)
        if (g.get('authorized') is not True or g.get('read_only') is not True
                or g.get('MES_actions') != 0 or g.get('profile') != ref(self.profile_path)
                or g.get('bridge_source_freeze') != p['bridge_source_freeze']
                or g.get('catalog_SHA256') != p['case_catalog']['expected_DB_SHA256']
                or g.get('lease_profile') != {'path': p['lease']['profile_path'], 'sha256': p['lease']['expected_SHA256']}
                or g.get('producer') != 'workbench_local_fullworld_v1'
                or not isinstance(g.get('allowed_dataset_ids'), list) or not g['allowed_dataset_ids']
                or g.get('max_jobs') != 8 or not g['not_before'] <= time.time() < g['expires_at']
                or g['expires_at'] - g['not_before'] > 7200):
            raise ValueError('exact bounded startup delegation required')
        for key in ('actual_model_profile', 'model_sourcefreeze', 'data_parent_profile',
                    'data_parent_sourcefreeze', 'component'):
            if g.get(key) != p[key]:
                raise ValueError('startup profile/source/component binding mismatch')
            checked(p[key])
        checked(g['lease_profile'])

    def catalog(self):
        self.admit_startup()
        p = self.profile
        import yaml
        component = yaml.safe_load(Path(checked(p['component'])).read_text(encoding='utf-8'))
        configured_path = Path(component['paths'][p['case_catalog']['DB_from_component_path_key']])
        path = (Path(p['component']['path']).parent / configured_path).resolve()
        db_pin = {'path': str(path), 'sha256': p['case_catalog']['expected_DB_SHA256']}
        checked(db_pin)  # Expected bytes before opening SQLite, never inferred from current-at-start bytes.
        mapping = p['case_catalog']['schema_mapping']
        if any(not v.replace('_', '').isalnum() for v in mapping.values()):
            raise ValueError('configured SQL identifiers are invalid')
        connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            rows = connection.execute(f'SELECT {mapping["id"]},{mapping["payload"]} FROM {mapping["table"]} ORDER BY {mapping["id"]} LIMIT ?',
                                      (p['case_catalog']['max_rows'] + 1,)).fetchall()
        finally:
            connection.close()
        if len(rows) > p['case_catalog']['max_rows']:
            raise ValueError('catalog exceeds configured bound')
        result = []
        for case_id, text in rows:
            case = json.loads(text)
            if case.get('case_id') != case_id:
                raise ValueError('catalog primary key differs from payload case ID')
            if (case.get('direction') not in p['case_catalog']['allowed_directions']
                    or case.get('dataset_id') not in self.grant['allowed_dataset_ids']):
                continue
            metadata = {key: case.get(key) for key in p['case_catalog']['fields']}
            metadata['case_id'] = case_id
            token = digest({'DB': db_pin, 'case_id': case_id, 'row_sha256': hashlib.sha256(text.encode()).hexdigest()})
            result.append({'case_token': token, 'metadata': metadata})
        return {'cases': result, 'synthetic': True, 'metadata_is_authority': False,
                'selector_names': sorted({'equipment_candidate', 'trend_step', 'legend', 'metro_item',
                    'measure_channel', 'schema_term', 'history_chunk_id', 'query_image_id',
                    'process_steps', 'process_pass', 'metro_steps', 'metro_items'})}

    def submit(self, room, body):
        self.admit_startup()
        validate_body(body)
        entries = {r['case_token']: r for r in self.catalog()['cases']}
        selected = entries.get(body['case_token'])
        if selected is None:
            raise ValueError('stale or unknown catalog selection')
        request = {'case_id': selected['metadata']['case_id'], 'question': body['question'],
                   'selectors': body['selectors']}
        envelope = {'original_request': request, 'catalog': selected,
                    'catalog_SHA256': self.profile['case_catalog']['expected_DB_SHA256']}
        return self.store.enqueue(room, body['client_request_id'], envelope, self.grant['grant_id'],
                                  self.grant['max_jobs'], self.grant['expires_at'])

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name='local-fullworld-research')
            self.thread.start()

    def close(self):
        self.stop_event.set()  # Active detached wrapper retains its lease and artifacts.

    def _loop(self):
        while not self.stop_event.wait(0.5):
            job = self.store.claim()
            if job is None:
                continue
            try:
                self._execute(job)
            except Exception as exc:
                self.store.finish(job['job_id'], 'FAILED', {'error_type': type(exc).__name__, 'error': str(exc),
                                                          'no_automatic_retry': True})

    def _execute(self, job):
        self.admit_startup()
        if time.time() - job['created'] > 3600:
            raise ValueError('queue wait limit exceeded')
        p = self.profile
        catalog = {r['case_token']: r for r in self.catalog()['cases']}
        selected = job['request']['catalog']
        if catalog.get(selected['case_token']) != selected:
            raise ValueError('queued catalog selection changed before dispatch')
        root = Path(p['job_spool']).resolve()
        root.mkdir(parents=True, exist_ok=True)
        size = sum(f.stat().st_size for f in root.rglob('*') if f.is_file())
        size += sum(f.stat().st_size for f in Path(p['job_DB']).parent.glob(Path(p['job_DB']).name + '*') if f.is_file())
        if size + p['artifact_cap']['reservation_per_job'] > p['artifact_cap']['bytes']:
            raise ValueError('research artifact cap reservation unavailable; no evidence deletion')
        directory = root / job['job_id']
        directory.mkdir(exist_ok=False)
        request = directory / 'request.json'
        write(request, job['request']['original_request'])
        intent = {'run_id': job['job_id'], 'request': ref(request), 'envelope': job['request'],
                  'startup_grant': self.grant_pin, 'profile': ref(self.profile_path),
                  'GPU_owner': 'workbench:' + job['job_id'], 'producer': 'workbench_local_fullworld_v1'}
        write(directory / 'intent.json', intent)
        command = [p['lab_interpreter'], '-m', 'qmodels.research_gpu_lease_v1', '--profile',
                   p['lease']['profile_path'], '--profile-sha', p['lease']['expected_SHA256'],
                   '--intent', str(directory / 'intent.json'), '--intent-sha', ref(directory / 'intent.json')['sha256']]
        env = os.environ.copy()
        env.update(PYTHONUTF8='1', PYTHONPATH=str(Path(p['lab_base_config']).parent.parent / 'src'),
                   HF_DEACTIVATE_ASYNC_LOAD='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
        with (directory / 'wrapper.stdout.log').open('xb') as out, (directory / 'wrapper.stderr.log').open('xb') as err:
            worker = subprocess.Popen(command, env=env, cwd=Path(p['lab_base_config']).parent.parent,
                                      stdout=out, stderr=err, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            import psutil
            wrapper_front = {'pid': worker.pid, 'creation_time': psutil.Process(worker.pid).create_time()}
            write(directory / 'wrapper-launch.json', {'front': wrapper_front, 'command': command,
                  'server': {'pid': os.getpid(), 'creation_time': psutil.Process().create_time()}})
            with self.store.connect() as db:
                db.execute("UPDATE jobs SET result=? WHERE id=? AND state='WAITING_GPU'",
                           (json.dumps({'wrapper_pid': worker.pid, 'GPU_admitted': False,
                                        'trace_incomplete': True}), job['job_id']))
                self.store.event(db, job['job_id'], {'event': 'wrapper_started', 'wrapper_pid': worker.pid,
                                                    'GPU_admitted': False, 'state': 'WAITING_GPU'})
            observed = set()
            while worker.poll() is None:
                self._mark_running_if_admitted(job['job_id'], directory, worker.pid)
                for f in sorted(directory.glob('call-*.*.json')):
                    if f.name in observed:
                        continue
                    try:
                        value = read(f)
                    except (ValueError, OSError):
                        continue
                    if f.name.endswith(('.input.json', '.raw.json')):
                        with self.store.connect() as db:
                            self.store.event(db, job['job_id'], {'event': 'actual_role_artifact', 'name': f.name,
                                                               'sha256': ref(f)['sha256']})
                        observed.add(f.name)
                time.sleep(0.25)
            code = worker.returncode
        receipt = read(directory / 'receipt.json') if (directory / 'receipt.json').exists() else None
        successful = code == 0 and receipt and not str(receipt.get('status', '')).startswith('FAILED')
        self.store.finish(job['job_id'], 'SUCCEEDED_TRACE' if successful else 'FAILED',
                          {'exit_code': code, 'receipt': receipt, 'quality_verified': False,
                           'trace_incomplete': not bool(receipt), 'artifacts': self.artifact_index(job['job_id'])})

    def _mark_running_if_admitted(self, job_id, directory, wrapper_pid):
        """Only complete, matching lease and worker admission evidence can advance the UI state."""
        import psutil
        try:
            lease = read(directory / 'lease-admission.json')
            start = read(directory / 'worker-start.json')
            intent = read(directory / 'intent.json')
            owner = read(self.profile['lease']['owner_record'])
        except (OSError, ValueError):
            return False  # A partially written JSON file is not admission evidence.
        if (lease.get('path') != self.profile['lease']['owner_record']
                or lease.get('owner') != 'workbench:' + job_id
                or lease.get('launch_state') != 'READY' or not lease.get('nonce')
                or owner.get('child') != lease.get('child_front')
                or owner.get('state') != 'ACTIVE'
                or any(owner.get(k) != lease.get(k) for k in ('owner', 'nonce', 'wrapper_pid', 'wrapper_creation_time'))
                or start.get('intent') != ref(directory / 'intent.json')
                or start.get('request') != intent.get('request')
                or start.get('startup_grant') != intent.get('startup_grant')
                or start.get('model_profile') != self.profile['actual_model_profile']
                or start.get('parent_profile') != self.profile['data_parent_profile']
                or start.get('new_action_commits') != 0):
            return False
        try:
            launch = read(directory / 'wrapper-launch.json')
            if launch['front']['pid'] != wrapper_pid or launch['server']['pid'] != os.getpid():
                return False
            import importlib.util
            pin = self.profile['process_guard_source']
            if pin not in self.source['files']:
                return False
            spec = importlib.util.spec_from_file_location('research_process_guard_' + pin['sha256'], checked(pin))
            guard = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(guard)
            proof = guard.validate_python_chain(launch['front'], lease['wrapper_pid'], launch['server'],
                        launch['command'], self.profile['python_launch_chain'])
            if start['lease_admission'] != ref(directory / 'lease-admission.json'):
                return False
            driver_proof = guard.validate_python_chain(lease['child_front'], start['process']['pid'],
                        {'pid': lease['wrapper_pid'], 'creation_time': lease['wrapper_creation_time']},
                        owner['child']['command'], self.profile['python_launch_chain'],
                        parent_command=launch['command'])
            if driver_proof.get('actual') is not None and driver_proof['actual'] != start['process']:
                return False
        except (OSError, ValueError, KeyError, psutil.Error):
            return False
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = {'wrapper_pid': wrapper_pid, 'GPU_admitted': True, 'trace_incomplete': True,
                      'wrapper_process_proof': proof,
                      'driver_process_proof': driver_proof,
                      'lease_admission': ref(directory / 'lease-admission.json'),
                      'worker_start': ref(directory / 'worker-start.json')}
            changed = db.execute("UPDATE jobs SET state='RUNNING',result=? WHERE id=? AND state='WAITING_GPU'",
                                 (json.dumps(result), job_id)).rowcount
            if changed:
                self.store.event(db, job_id, {'event': 'worker_admitted', 'state': 'RUNNING', **result})
            return bool(changed)

    def artifact_index(self, job):
        root = Path(self.profile['job_spool']) / job
        names = {'validated_report_json': 'validated-facts-and-coverage.json',
                 'validated_report_md': 'validated-facts-and-coverage.md',
                 'coverage': 'planned-capability-coverage.md', 'receipt': 'receipt.json'}
        return {key: ref(root / name) for key, name in names.items() if (root / name).is_file()}

    def artifact(self, room, job, name):
        self.store.get(room, job)
        index = self.artifact_index(job)
        if name == 'raw_index':
            return {'artifacts': [ref(p) for p in sorted((Path(self.profile['job_spool']) / job).glob('call-*.json'))]}
        if name not in index:
            raise ValueError('unknown or unavailable research artifact')
        pin = index[name]
        checked(pin)
        return {'artifact': pin, 'content': Path(pin['path']).read_text(encoding='utf-8'),
                'model_prose_reviewed': False}
