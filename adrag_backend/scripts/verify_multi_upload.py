"""Opt-in real upload verification; preserves jobs and documents for inspection.

Prepare fixtures: python scripts/verify_multi_upload.py
Run: python scripts/verify_multi_upload.py --run --collection <qdrant_name>
Resume polling without resubmitting: add --resume to the same run command.
Credentials: API_ADMIN_ID / API_ADMIN_PASSWORD in environment or repository .env.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import fitz
import httpx
from docx import Document
from dotenv import load_dotenv
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for index in range(1, 11):
        marker = f"MULTIUPLOAD-{directory.name}-{index:02d}"
        lines = [f"Safety verification document {index}", f"Reference: {marker}",
                 "Inspect the emergency exit before starting work.",
                 "Check protective gloves and safety glasses every morning.",
                 "Report damaged equipment to the safety supervisor."]
        suffix = '.pdf' if index <= 4 else '.docx' if index <= 6 else '.xlsx' if index <= 8 else '.png'
        path = directory / f"{index:02d}-safety{suffix}"
        if not path.exists():
            if suffix == '.pdf':
                with fitz.open() as document:
                    page = document.new_page()
                    page.insert_text((50, 70), '\n\n'.join(lines), fontsize=13)
                    document.save(path)
            elif suffix == '.docx':
                document = Document()
                document.add_heading(lines[0], 0)
                for line in lines[1:]:
                    document.add_paragraph(line)
                document.save(path)
            elif suffix == '.xlsx':
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = 'Safety checklist'
                sheet.append(['Reference', 'Inspection item', 'Result'])
                for line in lines[2:]:
                    sheet.append([marker, line, 'Verified'])
                workbook.save(path)
                workbook.close()
            else:
                image = Image.new('RGB', (1600, 650), 'white')
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 30)
                draw.multiline_text((50, 60), '\n\n'.join(lines), fill='black', font=font)
                image.save(path)
        files.append({'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return files


def verify(args):
    load_dotenv(ROOT / '.env')
    directory = ROOT / 'artifacts' / 'multi-upload-verification' / args.run_id
    if directory.resolve().parent != (ROOT / 'artifacts' / 'multi-upload-verification').resolve():
        raise ValueError('run-id must be a single directory name')
    files = prepare(directory)
    report_path = directory / 'report.json'
    if not args.run:
        print(json.dumps({'prepared_files': len(files), 'directory': str(directory)}))
        return
    if not args.collection:
        raise ValueError('--collection is required; specify the test collection qdrant_name')
    user_id, password = os.getenv('API_ADMIN_ID'), os.getenv('API_ADMIN_PASSWORD')
    if not user_id or not password:
        raise ValueError('Configure API_ADMIN_ID and API_ADMIN_PASSWORD before running')
    if report_path.exists() and not args.resume:
        raise ValueError('A report already exists. Use --resume to avoid duplicate uploads.')
    if args.resume and not report_path.exists():
        raise ValueError('No report to resume')
    base_url = os.getenv('API_BASE_URL', 'http://127.0.0.1:8081/api').rstrip('/')
    report = json.loads(report_path.read_text(encoding='utf-8')) if args.resume else {
        'api_base_url': base_url, 'collection': args.collection, 'files': files, 'jobs': [], 'status': 'started',
    }
    if report['api_base_url'] != base_url or report['collection'] != args.collection:
        raise ValueError('Resume target does not match the saved report')

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    with httpx.Client(base_url=base_url, timeout=30) as api:
        login = api.post('/auth/login', json={'user_id': user_id, 'password': password})
        login.raise_for_status()
        api.headers['Authorization'] = f"Bearer {login.json()['access_token']}"
        collections = api.get('/collections', params={'include_all': 'true'})
        collections.raise_for_status()
        if args.collection not in {c['qdrant_name'] for c in collections.json()['collections']}:
            raise ValueError('Test collection is not accessible or does not exist')
        save()
        if not args.resume:
            for entry in files:
                job = {'filename': entry['filename'], 'status': 'submission_unknown'}
                report['jobs'].append(job)
                save()  # Preserve uncertain submission even if the response is lost.
                with (directory / entry['filename']).open('rb') as stream:
                    response = api.post('/ingest/upload', data={
                        'collection_name': args.collection, 'parser_type': 'docling', 'document_type': 'auto',
                    }, files={'file': (entry['filename'], stream)}, timeout=300)
                if response.status_code != 202:
                    job['http_status'] = response.status_code
                    save()
                    raise RuntimeError(f"Upload returned {response.status_code}; inspect report before resubmitting")
                job.update(response.json())
                save()
                print(f"accepted {job['filename']} job={job['job_id']}", flush=True)
        deadline = time.monotonic() + args.max_wait
        while time.monotonic() < deadline:
            pending = [j for j in report['jobs'] if j.get('job_id') and j['status'] not in ('completed', 'failed')]
            if not pending:
                break
            for job in pending:
                response = api.get(f"/ingest/jobs/{quote(job['job_id'], safe='')}")
                response.raise_for_status()
                job.update(response.json())
            save()
            print('states:', {state: sum(j['status'] == state for j in report['jobs'])
                              for state in ('queued', 'running', 'completed', 'failed')}, flush=True)
            time.sleep(3)
        report['status'] = 'verifying'
        save()
        if len(report['jobs']) != 10 or any(j['status'] != 'completed' for j in report['jobs']):
            raise RuntimeError('Not all 10 jobs completed; saved report can be resumed without resubmission')
        response = api.get('/ingest/documents', params={'collection_name': args.collection})
        response.raise_for_status()
        listed = {d['document_id'] for d in response.json()['documents']}
        document_ids = [j['result']['document_id'] for j in report['jobs']]
        assert len(set(document_ids)) == 10
        with httpx.Client(base_url=os.getenv('API_QDRANT_URL', 'http://127.0.0.1:6333'), timeout=30) as qdrant:
            for job, entry in zip(report['jobs'], files):
                document_id = job['result']['document_id']
                assert document_id in listed
                original = api.get(f'/ingest/documents/{quote(document_id, safe="")}/file')
                original.raise_for_status()
                assert hashlib.sha256(original.content).hexdigest() == entry['sha256']
                count = qdrant.post(f'/collections/{quote(args.collection, safe="")}/points/count', json={
                    'exact': True, 'filter': {'must': [{'key': 'document_id', 'match': {'value': document_id}}]},
                })
                count.raise_for_status()
                job['verified_vector_count'] = count.json()['result']['count']
                assert job['verified_vector_count'] > 0
                job['original_sha256_matches'] = True
                save()
        report['status'] = 'passed_upload_list_original_vector_checks'
        save()
        print(f'PASS: {report_path}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--collection')
    parser.add_argument('--run-id', default='batch-10-20260907')
    parser.add_argument('--max-wait', type=int, default=3600)
    verify(parser.parse_args())
