const OPEN_XML_EXTENSIONS = new Set(['xlsx', 'xlsm', 'xltx', 'xltm']);
const EXTERNAL_FORMULA_PATTERN = /\[\d+\]|\[[^\]]+\.(?:xlsx?|xlsm|xlsb|xltx|xltm)\]/i;

const extensionOf = (filename) => String(filename || '').split('.').pop()?.toLowerCase() || '';
const attributeValue = (attributes, name) => {
  const match = String(attributes || '').match(new RegExp(`\\b${name}=["']([^"']+)["']`, 'i'));
  return match?.[1] || '';
};

const removeRelationships = (xml, relationshipTypes) => {
  return xml.replace(/<Relationship\b[^>]*\/?\s*>/gi, (relationship) => {
    const type = attributeValue(relationship, 'Type');
    return relationshipTypes.some((suffix) => type.endsWith(suffix)) ? '' : relationship;
  });
};

const removeExternalFormulaTags = (xml) => {
  const formulaPattern = /<f\b([^>]*?)(?:\/\s*>|>([\s\S]*?)<\/f>)/gi;
  const externalSharedIndexes = new Set();

  for (const match of xml.matchAll(formulaPattern)) {
    if (!EXTERNAL_FORMULA_PATTERN.test(match[2] || '')) continue;
    const sharedIndex = attributeValue(match[1], 'si');
    if (sharedIndex) externalSharedIndexes.add(sharedIndex);
  }

  return xml.replace(formulaPattern, (formula, attributes, content = '') => {
    const sharedIndex = attributeValue(attributes, 'si');
    return EXTERNAL_FORMULA_PATTERN.test(content) || (sharedIndex && externalSharedIndexes.has(sharedIndex)) ? '' : formula;
  });
};

const updateTextEntry = async (archive, path, transform) => {
  const entry = archive.file(path);
  if (!entry) return false;
  const source = await entry.async('string');
  const updated = transform(source);
  if (source === updated) return false;
  archive.file(path, updated);
  return true;
};

// 2026.10.23(woojin.jung) 수정 - 그림·도형·서식을 보존하면서 외부 통합 문서 연결만 제거한 안전한 Excel 사본 생성
export const createSafeExcelCopy = async (fileData, filename) => {
  if (!OPEN_XML_EXTENSIONS.has(extensionOf(filename))) {
    throw new Error('SAFE_COPY_UNSUPPORTED_FORMAT');
  }

  const { default: JSZip } = await import('jszip');
  const archive = await JSZip.loadAsync(fileData);

  await updateTextEntry(archive, 'xl/workbook.xml', (xml) => {
    return xml
      .replace(/<(?:\w+:)?externalReferences\b[^>]*>[\s\S]*?<\/(?:\w+:)?externalReferences>/gi, '')
      .replace(/<(?:\w+:)?externalReferences\b[^>]*\/\s*>/gi, '')
      .replace(/<(?:\w+:)?definedName\b[^>]*>[\s\S]*?<\/(?:\w+:)?definedName>/gi, (definedName) => {
        return EXTERNAL_FORMULA_PATTERN.test(definedName) ? '' : definedName;
      });
  });

  await updateTextEntry(archive, 'xl/_rels/workbook.xml.rels', (xml) => {
    return removeRelationships(xml, ['/externalLink', '/calcChain']);
  });

  const worksheetPaths = Object.keys(archive.files).filter((path) => /^xl\/worksheets\/sheet\d+\.xml$/i.test(path));
  await Promise.all(worksheetPaths.map(async (path) => {
    await updateTextEntry(archive, path, (xml) => removeExternalFormulaTags(xml));
  }));

  Object.keys(archive.files).forEach((path) => {
    if (/^xl\/externalLinks\//i.test(path) || /^xl\/calcChain\.xml$/i.test(path)) archive.remove(path);
  });

  await updateTextEntry(archive, '[Content_Types].xml', (xml) => {
    return xml.replace(/<Override\b[^>]*\/\s*>/gi, (override) => {
      const partName = attributeValue(override, 'PartName');
      return /^\/(?:xl\/externalLinks\/|xl\/calcChain\.xml$)/i.test(partName) ? '' : override;
    });
  });

  return archive.generateAsync({
    type: 'arraybuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
};

