<template>
  <div v-if="table?.rows?.length" class="table-wrap">
    <table><thead><tr><th v-for="column in columns" :key="column">{{ label(column) }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in table.rows" :key="rowIndex"><td v-for="column in columns" :key="column">{{ value(row, column) }}</td></tr></tbody></table>
  </div>
  <p v-else class="empty-note">{{ emptyText }}</p>
</template>

<script setup>
import { computed } from 'vue';
const props = defineProps({ table: { type: Object, default: null }, emptyText: { type: String, default: '표 데이터가 없습니다.' } });
const labels = { item_no: '번호', revision: 'REV', rev: '개정', part_no: '품번', part_name: '품명', qty: '수량', material: '재질', material_group: '재질 그룹', part_spec: '사양', after_treatment: '후처리', description: '내용', date: '날짜', drawn: '작성', checked: '검토' };
const columns = computed(() => props.table?.columns?.map((column) => typeof column === 'string' ? column : column.key || column.name).filter(Boolean) || Object.keys(props.table?.rows?.[0] || {}));
const label = (column) => labels[column] || column;
const value = (row, column) => { const result = row?.[column]; return result === null || result === undefined || result === '' ? '-' : String(result); };
</script>

<style scoped>
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:.8rem}th,td{padding:.5rem .6rem;border:1px solid #e2e8f0;text-align:left;white-space:nowrap}th{background:#f8fafc;color:#475569;font-weight:600}td{color:#334155}.empty-note{padding:1rem;border:1px dashed #cbd5e1;border-radius:8px;background:#f8fafc;color:#64748b;text-align:center;font-size:.84rem}
</style>
