<template>
  <Teleport to="body">
    <Transition name="app-tooltip">
      <div
        v-if="visible"
        id="app-global-tooltip"
        ref="tooltipRef"
        class="app-tooltip"
        :class="`is-${placement}`"
        :style="tooltipStyle"
        role="tooltip"
      >
        <span class="app-tooltip-mark" aria-hidden="true">?</span>
        <span class="app-tooltip-text">{{ message }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const TOOLTIP_ID = 'app-global-tooltip'
const TOOLTIP_GAP = 11
const VIEWPORT_GAP = 10

const tooltipRef = ref(null)
const visible = ref(false)
const message = ref('')
const placement = ref('top')
const tooltipStyle = ref({ top: '0px', left: '0px', '--tooltip-arrow-x': '50%' })

let activeTarget = null
let mutationObserver = null
let showTimer = null
let hideTimer = null

function prepareElement(element) {
  if (!(element instanceof HTMLElement)) return

  const nativeTitle = element.getAttribute('title')
  if (nativeTitle === null) return

  const text = nativeTitle.trim()
  if (text) element.dataset.appTooltip = text
  else delete element.dataset.appTooltip

  // Remove the native browser bubble after preserving its content for our UI.
  element.removeAttribute('title')
}

function prepareTree(root) {
  if (!(root instanceof Element)) return
  prepareElement(root)
  root.querySelectorAll('[title]').forEach(prepareElement)
}

function tooltipTarget(eventTarget) {
  if (!(eventTarget instanceof Element)) return null
  const target = eventTarget.closest('[data-app-tooltip]')
  return target instanceof HTMLElement && target.dataset.appTooltip?.trim() ? target : null
}

function setDescribedBy(target, enabled) {
  const ids = new Set((target.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean))
  if (enabled) ids.add(TOOLTIP_ID)
  else ids.delete(TOOLTIP_ID)

  if (ids.size) target.setAttribute('aria-describedby', [...ids].join(' '))
  else target.removeAttribute('aria-describedby')
}

function positionTooltip() {
  if (!activeTarget || !tooltipRef.value) return
  if (!activeTarget.isConnected) {
    hide(true)
    return
  }

  const targetRect = activeTarget.getBoundingClientRect()
  const tooltipRect = tooltipRef.value.getBoundingClientRect()
  const canPlaceAbove = targetRect.top >= tooltipRect.height + TOOLTIP_GAP + VIEWPORT_GAP
  const nextPlacement = canPlaceAbove ? 'top' : 'bottom'
  const idealLeft = targetRect.left + targetRect.width / 2 - tooltipRect.width / 2
  const maxLeft = Math.max(VIEWPORT_GAP, window.innerWidth - tooltipRect.width - VIEWPORT_GAP)
  const left = Math.min(Math.max(idealLeft, VIEWPORT_GAP), maxLeft)
  const top = canPlaceAbove
    ? targetRect.top - tooltipRect.height - TOOLTIP_GAP
    : targetRect.bottom + TOOLTIP_GAP
  const arrowX = Math.min(
    Math.max(targetRect.left + targetRect.width / 2 - left, 16),
    tooltipRect.width - 16,
  )

  placement.value = nextPlacement
  tooltipStyle.value = {
    top: `${Math.round(top)}px`,
    left: `${Math.round(left)}px`,
    '--tooltip-arrow-x': `${Math.round(arrowX)}px`,
  }
}

function show(target, immediate = false) {
  window.clearTimeout(hideTimer)
  window.clearTimeout(showTimer)

  const open = async () => {
    if (activeTarget && activeTarget !== target) setDescribedBy(activeTarget, false)
    activeTarget = target
    message.value = target.dataset.appTooltip.trim()
    visible.value = true
    setDescribedBy(target, true)
    await nextTick()
    positionTooltip()
  }

  if (immediate) open()
  else showTimer = window.setTimeout(open, 160)
}

function hide(immediate = false) {
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)

  const close = () => {
    if (activeTarget) setDescribedBy(activeTarget, false)
    activeTarget = null
    visible.value = false
  }

  if (immediate) close()
  else hideTimer = window.setTimeout(close, 80)
}

function onPointerOver(event) {
  const target = tooltipTarget(event.target)
  if (!target || target === activeTarget) return
  show(target)
}

function onPointerOut(event) {
  const previousTarget = tooltipTarget(event.target)
  const nextTarget = tooltipTarget(event.relatedTarget)
  if (previousTarget && nextTarget !== previousTarget) hide()
}

function onFocusIn(event) {
  const target = tooltipTarget(event.target)
  if (target) show(target, true)
}

function onFocusOut(event) {
  if (activeTarget && event.target === activeTarget) hide(true)
}

function onKeyDown(event) {
  if (event.key === 'Escape') hide(true)
}

function onViewportChange() {
  if (visible.value) positionTooltip()
}

onMounted(() => {
  prepareTree(document.body)

  mutationObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes') prepareElement(mutation.target)
      mutation.addedNodes.forEach((node) => prepareTree(node))
    })
    if (activeTarget && !activeTarget.isConnected) hide(true)
  })
  mutationObserver.observe(document.body, {
    attributes: true,
    attributeFilter: ['title'],
    childList: true,
    subtree: true,
  })

  document.addEventListener('pointerover', onPointerOver, true)
  document.addEventListener('pointerout', onPointerOut, true)
  document.addEventListener('focusin', onFocusIn, true)
  document.addEventListener('focusout', onFocusOut, true)
  document.addEventListener('keydown', onKeyDown, true)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})

onBeforeUnmount(() => {
  mutationObserver?.disconnect()
  window.clearTimeout(showTimer)
  window.clearTimeout(hideTimer)
  document.removeEventListener('pointerover', onPointerOver, true)
  document.removeEventListener('pointerout', onPointerOut, true)
  document.removeEventListener('focusin', onFocusIn, true)
  document.removeEventListener('focusout', onFocusOut, true)
  document.removeEventListener('keydown', onKeyDown, true)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<style scoped>
.app-tooltip {
  position: fixed;
  z-index: 10000;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: max-content;
  max-width: min(320px, calc(100vw - 20px));
  padding: 9px 12px 10px 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: linear-gradient(145deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.98));
  box-shadow:
    0 14px 32px rgba(15, 23, 42, 0.2),
    0 4px 10px rgba(15, 23, 42, 0.12);
  color: #f8fafc;
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
  pointer-events: none;
}

.app-tooltip::after {
  position: absolute;
  left: var(--tooltip-arrow-x);
  width: 9px;
  height: 9px;
  border-right: 1px solid rgba(148, 163, 184, 0.14);
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: #111c30;
  content: '';
}

.app-tooltip.is-top::after {
  bottom: -5px;
  transform: translateX(-50%) rotate(45deg);
}

.app-tooltip.is-bottom::after {
  top: -5px;
  transform: translateX(-50%) rotate(225deg);
}

.app-tooltip-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border: 1px solid rgba(147, 197, 253, 0.25);
  border-radius: 6px;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 3px 8px rgba(37, 99, 235, 0.28);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.app-tooltip-text {
  min-width: 0;
}

.app-tooltip-enter-active,
.app-tooltip-leave-active {
  transition:
    opacity 0.14s ease,
    transform 0.14s ease;
}

.app-tooltip-enter-from,
.app-tooltip-leave-to {
  opacity: 0;
  transform: translateY(3px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .app-tooltip-enter-active,
  .app-tooltip-leave-active {
    transition: none;
  }
}
</style>
