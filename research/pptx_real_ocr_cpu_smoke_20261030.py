from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse, ctypes, hashlib, importlib.util, json, os, shutil, socket, stat, sys
from ctypes import wintypes
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / 'var' / 'ocr-runtime-20261030'
EXPECTED = '합성 OCR 테스트입니다'

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('BasicLimitInformation',BASIC_LIMIT),('IoInfo',IO_COUNTERS),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def hasharg(v, label):
    if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdefABCDEF' for c in v): raise RuntimeError(label+' must be 64 hex chars')
    return v.lower()
def install_job_cap():
    k=ctypes.WinDLL('kernel32',use_last_error=True); k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]; k.CreateJobObjectW.restype=wintypes.HANDLE; k.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]; k.SetInformationJobObject.restype=wintypes.BOOL; k.GetCurrentProcess.restype=wintypes.HANDLE; k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]; k.AssignProcessToJobObject.restype=wintypes.BOOL
    h=k.CreateJobObjectW(None,None)
    if not h: raise OSError(ctypes.get_last_error(),'CreateJobObjectW')
    i=EXT_LIMIT(); i.BasicLimitInformation.LimitFlags=0x100|0x200; i.ProcessMemoryLimit=i.JobMemoryLimit=1536*1024*1024
    if not k.SetInformationJobObject(h,9,ctypes.byref(i),ctypes.sizeof(i)) or not k.AssignProcessToJobObject(h,k.GetCurrentProcess()): raise OSError(ctypes.get_last_error(),'Job Object limit/assignment')
    return k,h
def checked(root,p):
    rr=root.resolve(strict=True); pp=p.resolve(strict=True)
    if not pp.is_relative_to(rr) or not pp.is_file(): raise RuntimeError('path outside trusted runtime: '+str(p))
    return pp
def module_origin(name,venv):
    s=importlib.util.find_spec(name)
    if s is None: raise RuntimeError('missing module '+name)
    origins=([s.origin] if s.origin and s.origin not in ('built-in','frozen') else [])+list(s.submodule_search_locations or ())
    if not origins or any(not Path(o).resolve().is_relative_to(venv) for o in origins): raise RuntimeError('module outside configured venv: '+name)
    return str(Path(origins[0]).resolve())
def output_dir():
    base=PROJECT_ROOT/'var'
    for i in range(1,10000):
        p=base/f'pptx-real-ocr-cpu-20261030-{i:04d}'
        try: p.mkdir(); return p
        except FileExistsError: continue
    raise RuntimeError('no exclusive output directory available')
def make_pptx(path,png):
    entries={
      '[Content_Types].xml':'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>',
      '_rels/.rels':'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
      'ppt/presentation.xml':'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>',
      'ppt/_rels/presentation.xml.rels':'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>',
      'ppt/slides/slide1.xml':'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:pic><p:nvPicPr><p:cNvPr id="2" name="Synthetic OCR image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr/></p:pic></p:spTree></p:cSld></p:sld>',
      'ppt/slides/_rels/slide1.xml.rels':'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/></Relationships>'}
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
      for n,v in entries.items(): z.writestr(n,v.encode())
      z.writestr('ppt/media/image1.png',png)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--expected-config-sha256',required=True); ap.add_argument('--expected-image-sha256',required=True); a=ap.parse_args(); ec=hasharg(a.expected_config_sha256,'config hash'); ei=hasharg(a.expected_image_sha256,'image hash')
    if os.name!='nt': raise RuntimeError('Windows Job Object required')
    disk=shutil.disk_usage('D:\\').free
    if disk<20*1024**3: raise RuntimeError('D: free space below 20 GiB')
    class MEM(ctypes.Structure): _fields_=[('dwLength',wintypes.DWORD),('dwMemoryLoad',wintypes.DWORD),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
    k=ctypes.WinDLL('kernel32',use_last_error=True); k.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MEM)]; k.GlobalMemoryStatusEx.restype=wintypes.BOOL; m=MEM(); m.dwLength=ctypes.sizeof(m)
    if not k.GlobalMemoryStatusEx(ctypes.byref(m)) or m.ullAvailPageFile<4*1024**3: raise RuntimeError('commit headroom below 4 GiB or unavailable')
    job_kernel,job_handle=install_job_cap()
    for n in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','ORT_NUM_THREADS'): os.environ[n]='1'
    def blocked(*_a,**_k): raise RuntimeError('network disabled by socket connect/connect_ex guard')
    socket.socket.connect=blocked; socket.socket.connect_ex=blocked
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    venv=(ROOT/'venv').resolve(strict=True); py=(venv/'Scripts'/'python.exe').resolve(strict=True)
    if Path(sys.executable).resolve(strict=True)!=py: raise RuntimeError('runner must use configured venv interpreter: '+str(py))
    out=output_dir(); pre={n:module_origin(n,venv) for n in ('numpy','onnxruntime','PIL','rapidocr','yaml')}
    import numpy, onnxruntime, yaml
    from PIL import Image
    from rapidocr import RapidOCR
    paths={n:str(Path(sys.modules[n].__file__).resolve()) for n in ('numpy','onnxruntime','PIL','rapidocr','yaml')}
    if any(not Path(p).is_relative_to(venv) for p in paths.values()): raise RuntimeError('imported module outside venv')
    manifest={}
    for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines(): d,r=line.split(maxsplit=1); manifest[r.strip()]=hasharg(d,'manifest '+r.strip())
    models=(ROOT/'models').resolve(strict=True); det=checked(ROOT,models/'ch_PP-OCRv5_det_mobile.onnx'); rec=checked(ROOT,models/'korean_PP-OCRv5_rec_mobile.onnx'); image=checked(ROOT,ROOT/'synthetic-ko.png'); config=checked(ROOT,ROOT/'rapidocr-ko.yaml')
    hashes={'detection':sha(det),'recognition':sha(rec),'image':sha(image),'config':sha(config)}
    if hashes['detection']!=manifest['models/ch_PP-OCRv5_det_mobile.onnx'] or hashes['recognition']!=manifest['models/korean_PP-OCRv5_rec_mobile.onnx']: raise RuntimeError('model SHA mismatch against trusted manifest')
    if hashes['config']!=ec or hashes['image']!=ei: raise RuntimeError('config/image SHA mismatch against recorded expected hash')
    cfg=yaml.safe_load(config.read_text(encoding='utf-8'))
    for section,model in (('Det',det),('Rec',rec)):
      if cfg.get(section,{}).get('engine_type')!='onnxruntime' or Path(cfg[section].get('model_path','')).resolve(strict=True)!=model: raise RuntimeError(section+' is not pinned to verified local ONNX file')
    if cfg.get('EngineConfig',{}).get('onnxruntime',{}).get('use_cuda') is not False: raise RuntimeError('ONNX CUDA must be explicitly false')
    engine=RapidOCR(config_path=str(config))
    from research.pptx_embedded_image_ocr_synthetic_20261030 import extract_pptx_embedded_image_ocr_candidates
    pptx=out/'synthetic-one-slide.pptx'
    if pptx.exists(): raise RuntimeError('refusing to overwrite fixture')
    make_pptx(pptx,image.read_bytes()); snapshot=sha(pptx)
    anchor='ppt/slides/slide1.xml#shape-2'
    metadata={'synthetic_fixture':True,'source_ref':'synthetic://pptx-ocr-ko','source_document_id':'synthetic-pptx-ko','source_version':'1','available_at':datetime(2026,10,29,tzinfo=timezone.utc),'anchor_chunk_ids':{anchor:'synthetic-existing-anchor-chunk'},}
    auth=[]
    def fake_authorize(meta): auth.append({'source_document_id':meta.get('source_document_id'),'anchor_id':meta.get('anchor_id')}); return True
    calls=[]
    def injected(payload): calls.append(hashlib.sha256(payload).hexdigest()); return engine(payload)
    result=extract_pptx_embedded_image_ocr_candidates(pptx_path=pptx,source_root=out,metadata=metadata,as_of=datetime(2026,10,30,tzinfo=timezone.utc),authorize_source=fake_authorize,engine=injected)
    providers={'detection':engine.text_det.session.session.get_providers(),'recognition':engine.text_rec.session.session.get_providers()}; candidates=result['candidates']; normalized=''.join(EXPECTED.split())
    c=candidates[0] if candidates else {}; text=''.join(x['text'] for x in c.get('ordered_text_confidence',[])); checks={
      'PPTX_snapshot_hash_matches_independent_hash':result['original_sha256']==snapshot==sha(pptx),
      'single_slide_picture_fixture_and_embedded_png_valid':len(candidates)==1 and c.get('image_sha256')==hashes['image'],
      'slide_ordinal_shape_anchor_and_presentation_order':c.get('slide_ordinal')==1 and c.get('slide_ordinal_status')=='presentation_order_resolved' and c.get('anchor_id')==anchor and c.get('picture_shape_id')=='2',
      'expected_korean_synthetic_text_recognized':normalized in ''.join(text.split()),
      'one_injected_rapidocr_call_for_one_image':len(calls)==1 and calls[0]==hashes['image'],
      'fake_source_and_anchor_authorization_invoked':len(auth)>=2 and any(x['anchor_id']==anchor for x in auth),
      'available_at_unknown_for_OCR_derived_candidate':c.get('available_at') is None and c.get('ocr_derivative_time_status')=='unverified',
      'CPU_only_providers_after_inference':providers=={'detection':['CPUExecutionProvider'],'recognition':['CPUExecutionProvider']},
      'coverage_remains_incomplete':result.get('coverage_status')=='incomplete_not_verified'}
    report={'status':'passed' if all(checks.values()) else 'failed','attempt':'synthetic_pptx_real_rapidocr_cpu_one_image','pptx_path':str(pptx),'pptx_sha256':snapshot,'independent_pptx_sha256':sha(pptx),'runtime_root':str(ROOT),'extractor':str(PROJECT_ROOT/'research'/'pptx_embedded_image_ocr_synthetic_20261030.py'),'output_directory':str(out),'module_paths':paths,'preimport_module_origins':pre,'sha256':hashes,'providers_after_inference':providers,'injected_ocr_call_count':len(calls),'authorization':'fake_allow_only','checks':checks,'synthetic_only':True,'candidate_count':len(candidates),'full_candidates':candidates,'limitations':result.get('limitations',[]),'execution_limitations':['engine model file actual loading causality is unverified; configured paths and bytes are verified but not bound to runtime session','real site ACL is unverified','existing Hybrid RAG and chunk/index integration are unverified','real internal materials and all-image OCR quality are unverified','synthetic fixture and fake authorization only','network guard blocks Python socket connect/connect_ex only; it is not OS network isolation','native dependency provenance and deployment bindings were not verified'],'network_guard':'socket connect/connect_ex only; not an OS firewall or OS-wide isolation','job_object_memory_cap_mib':1536,'thread_environment_cap':1,'commit_headroom_bytes_before_run':m.ullAvailPageFile,'disk_free_bytes_before_run':disk}
    rp=out/'result.json'
    with rp.open('x',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,indent=2); f.write('\n')
    _=job_kernel,job_handle,numpy,onnxruntime,Image
    if not all(checks.values()): raise AssertionError(', '.join(k for k,v in checks.items() if not v))
if __name__=='__main__': main()


