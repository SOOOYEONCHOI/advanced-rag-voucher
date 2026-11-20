<template>
  <router-view />
  <AppTooltip />
</template>

<script setup>
import AppTooltip from './components/AppTooltip.vue'
</script>

<style>
html,
body,
#app {
  width: 100%;
  height: 100%;
  margin: 0;
}

body {
  overflow: hidden;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

/* 터치 기기에서 입력 포커스 시 iOS 자동 확대 방지 (16px 미만이면 확대됨) */
@media (max-width: 1024px) and (pointer: coarse) {
  input:not([type='checkbox']):not([type='radio']):not([type='range']),
  select,
  textarea {
    font-size: 16px !important;
  }
}

*,
*::before,
*::after {
  box-sizing: border-box;
}
</style>
