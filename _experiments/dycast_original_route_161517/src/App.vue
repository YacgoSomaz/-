<template>
  <div class="app-shell">
    <nav class="app-tabs">
      <button :class="{ active: view === 'batch' }" type="button" @click="view = 'batch'">手动监听</button>
      <button :class="{ active: view === 'single' }" type="button" @click="view = 'single'">单房间调试</button>
    </nav>
    <BatchView v-if="view === 'batch'" />
    <IndexView v-else />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import BatchView from './views/BatchView.vue';
import IndexView from './views/IndexView.vue';
import { printInfo, printSKMCJ } from './utils/logUtil';

const view = ref<'batch' | 'single'>('batch');

setTimeout(() => {
  console?.clear();
  printSKMCJ();
  printInfo();
}, 1500);
</script>

<style lang="scss">
::selection {
  background-color: #8b968d;
  color: #fff;
}

.app-shell {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-tabs {
  height: 44px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 18px;
  border-bottom: 1px solid #cbd8d1;
  background: #fff;
  box-sizing: border-box;

  button {
    height: 30px;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0 12px;
    color: #496056;
    background: transparent;
    cursor: pointer;

    &.active {
      color: #1f3c2d;
      border-color: #aac3b4;
      background: #e9f1ec;
    }
  }
}

.app-shell > .batch-view,
.app-shell > .index-view {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
