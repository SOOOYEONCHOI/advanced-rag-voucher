// 2026.10.19(sooyeon.choi) 추가 - Phase 4-A 답변 사진(UI-03·UI-04): [IMG:ref] 렌더링, 스트리밍 중 미완성 태그, blob 캐시
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';

import {
  imageSourceLabel,
  removeImageTags,
  renderImageRefs,
  stripPartialImageTag,
} from '../src/utils/answerImages.js';

const images = [
  { ref: 'aaa111', resource_id: 'doc-v1-i0001', title: '09 FAN Step 6 Step 사진', sheet_name: '09 FAN', from_cell: 'B12', to_cell: 'D18' },
  { ref: 'bbb222', resource_id: 'doc-v1-i0002', title: '09 FAN 도면 "A"', sheet_name: '09 FAN', from_cell: 'F3', to_cell: 'F3' },
];

test('known refs become numbered badges and the list item gets thumbnails once', () => {
  const html = renderImageRefs(
    '<ol><li>체결합니다[1][IMG:aaa111] 다시[IMG:aaa111]</li><li>도면[IMG:bbb222]</li></ol>',
    images,
    { urls: { 'doc-v1-i0001': 'blob:one' } }
  );
  assert.equal((html.match(/class="image-ref"/g) || []).length, 3);
  assert.match(html, /data-image-ref="aaa111"[^>]*>.*?<\/i> 1<\/button>/);
  assert.match(html, /data-image-ref="bbb222"[^>]*>.*?<\/i> 2<\/button>/);
  assert.doesNotMatch(html, /\[IMG:/);
  // 썸네일은 사진마다 한 번, 목록 항목 안쪽 끝
  assert.equal((html.match(/class="answer-thumb"/g) || []).length, 2);
  assert.match(html, /<img src="blob:one"[^>]*><span class="thumb-caption">1\. 09 FAN Step 6 Step 사진<\/span><\/button><\/div><\/li>/);
  // URL이 아직 없으면 빈 썸네일, 제목의 따옴표는 이스케이프
  assert.match(html, /answer-thumb-empty/);
  assert.match(html, /title="09 FAN 도면 &quot;A&quot;"/);
});

test('paragraph thumbnails go after </p>, leftovers at the end', () => {
  const html = renderImageRefs('<p>체결[IMG:aaa111]</p><table><tr><td>도면[IMG:bbb222]</td></tr></table>', images);
  assert.match(html, /<\/p><div class="answer-inline-images">/);
  assert.match(html, /<\/table><div class="answer-inline-images">/);
  assert.equal(renderImageRefs('본문[IMG:aaa111]', images).endsWith('</div>'), true);
  assert.doesNotMatch(renderImageRefs('<p>본문[IMG:aaa111]</p>', images, { inline: false }), /answer-inline-images/);
});

test('refs missing from the validated list are removed; text without refs is unchanged', () => {
  assert.equal(renderImageRefs('<p>A[IMG:zzz999] B</p>', images), '<p>A B</p>');
  assert.equal(renderImageRefs('<p>A[IMG:aaa111]</p>', []), '<p>A</p>');
  assert.equal(renderImageRefs('<p>본문[1]</p>', images), '<p>본문[1]</p>');
  assert.equal(renderImageRefs('', images), '');
});

test('streaming hides a partial tag at the end only', () => {
  assert.equal(stripPartialImageTag('체결합니다[IMG:ab'), '체결합니다');
  assert.equal(stripPartialImageTag('체결합니다[IM'), '체결합니다');
  assert.equal(stripPartialImageTag('체결합니다['), '체결합니다');
  assert.equal(stripPartialImageTag('체결합니다[1]'), '체결합니다[1]');
  assert.equal(stripPartialImageTag('A[IMG:aaa111] B'), 'A[IMG:aaa111] B');
  assert.equal(removeImageTags('A[IMG:aaa111] B[IMG: bbb222 ]'), 'A B');
});

test('source label is sheet!range', () => {
  assert.equal(imageSourceLabel(images[0]), '09 FAN!B12:D18');
  assert.equal(imageSourceLabel(images[1]), '09 FAN!F3');
  assert.equal(imageSourceLabel({ sheet_name: '표지' }), '표지');
});

test('image blobs are fetched once per resource and failures are remembered', async () => {
  const server = await createServer({ server: { middlewareMode: true }, logLevel: 'silent' });
  try {
    const { useImageBlobs } = await server.ssrLoadModule('/src/composables/useImageBlobs.js');
    const calls = [];
    const revoked = [];
    const blobs = useImageBlobs({
      fetcher: async (id) => {
        calls.push(id);
        if (id === 'denied') throw { response: { status: 403 } };
        return `blob-of-${id}`;
      },
      createUrl: (blob) => `url:${blob}`,
      revokeUrl: (url) => revoked.push(url),
    });
    await Promise.all([blobs.ensure([{ resource_id: 'a' }, { resource_id: 'b' }]), blobs.ensure([{ resource_id: 'a' }])]);
    await blobs.ensure([{ resource_id: 'denied' }, null]);
    await blobs.ensure([{ resource_id: 'denied' }]);
    assert.deepEqual(calls.sort(), ['a', 'b', 'denied']);
    assert.equal(blobs.urls.a, 'url:blob-of-a');
    assert.equal(blobs.failed.denied, true);
    blobs.revokeAll();
    assert.deepEqual(revoked.sort(), ['url:blob-of-a', 'url:blob-of-b']);
    assert.equal(Object.keys(blobs.urls).length, 0);
  } finally {
    await server.close();
  }
});
