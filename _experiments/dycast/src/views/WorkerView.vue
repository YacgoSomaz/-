<template>
  <main class="worker-view">
    <section class="wk-header">
      <div>
        <p class="eyebrow">服务端管线 · 无浏览器采集</p>
        <h1>话术 + 弹幕后端控制台</h1>
      </div>
      <div class="header-actions">
        <input ref="fileInput" class="file-input" type="file" accept=".csv,.txt,text/csv" @change="handleFileChange" />
        <button class="btn secondary" type="button" @click="pickCsv">导入房间号</button>
        <button class="btn" type="button" :disabled="rooms.length === 0" @click="startAll">全部开始</button>
        <button class="btn danger" type="button" :disabled="activeCount === 0" @click="stopAll">全部停止</button>
        <a class="btn ghost" :href="exportCsvUrl" target="_blank" rel="noreferrer">导出 Excel</a>
      </div>
    </section>

    <section class="control-band">
      <label class="field">
        <span>后端地址</span>
        <input v-model="backendUrl" placeholder="http://127.0.0.1:8848" />
      </label>
      <label class="field compact">
        <span>新增直播号</span>
        <input v-model="newRid" placeholder="web_rid" @keydown.enter="addOne" />
      </label>
      <button class="btn secondary" type="button" :disabled="!newRid.trim()" @click="addOne">添加</button>
      <span class="conn" :class="{ ok: online }">{{ online ? '后端在线' : '后端未连接' }}</span>
    </section>

    <section class="stats-grid">
      <article class="stat"><span>房间数</span><strong>{{ rooms.length }}</strong></article>
      <article class="stat"><span>在监中</span><strong>{{ activeCount }}</strong></article>
      <article class="stat"><span>已连接</span><strong>{{ connectedCount }}</strong></article>
      <article class="stat"><span>弹幕事件</span><strong>{{ totalEvents }}</strong></article>
      <article class="stat"><span>话术段</span><strong>{{ totalSegments }}</strong></article>
    </section>

    <section class="log-panel">
      <div class="panel-title">
        <h2>托管状态</h2>
        <span>{{ online ? '每 3 秒刷新' : '检查后端地址 / 是否已启动 webui' }}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>状态</th><th>直播号</th><th>说明</th>
              <th>弹幕事件</th><th>话术段</th><th>最近录段</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="room in rooms" :key="room.rid">
              <td><span class="dot" :class="dotClass(room)"></span></td>
              <td class="mono">{{ room.rid }}</td>
              <td class="muted">{{ room.status }}</td>
              <td><strong>{{ room.events }}</strong></td>
              <td>{{ room.segments }}</td>
              <td class="muted">{{ fmtTs(room.last_segment_ts) }}</td>
              <td class="row-actions">
                <button v-if="!room.active" class="icon-btn" type="button" @click="startRoom(room.rid)">开始</button>
                <button v-else class="icon-btn danger-text" type="button" @click="stopRoom(room.rid)">停止</button>
                <button class="icon-btn danger-text" type="button" @click="delRoom(room.rid)">删除</button>
              </td>
            </tr>
            <tr v-if="rooms.length === 0">
              <td class="empty" colspan="7">导入房间号（CSV/txt，每行一个或含 room_num 列）后开始托管。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue';

interface WorkerRoom {
  rid: string;
  active: boolean;
  connected: boolean;
  status: string;
  events: number;
  segments: number;
  last_segment_ts: number;
}

const BACKEND_KEY = 'worker.backendUrl.v1';
const backendUrl = ref(localStorage.getItem(BACKEND_KEY) || 'http://127.0.0.1:8848');
const rooms = ref<WorkerRoom[]>([]);
const online = ref(false);
const newRid = ref('');
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInput');
let timer: number | undefined;

watch(backendUrl, v => localStorage.setItem(BACKEND_KEY, v));

const base = computed(() => backendUrl.value.replace(/\/$/, ''));
const exportCsvUrl = computed(() => `${base.value}/api/export/summary.csv`);
const activeCount = computed(() => rooms.value.filter(r => r.active).length);
const connectedCount = computed(() => rooms.value.filter(r => r.connected).length);
const totalEvents = computed(() => rooms.value.reduce((s, r) => s + r.events, 0));
const totalSegments = computed(() => rooms.value.reduce((s, r) => s + r.segments, 0));

function dotClass(r: WorkerRoom) {
  if (r.active && r.connected) return 'on';
  if (r.active) return 'warn';
  return 'off';
}

function fmtTs(t: number) {
  if (!t) return '—';
  return new Date(t * 1000).toLocaleTimeString('zh-CN', { hour12: false });
}

async function refresh() {
  try {
    const res = await fetch(`${base.value}/api/status`);
    const data = await res.json();
    rooms.value = (data.rooms || []) as WorkerRoom[];
    online.value = true;
  } catch {
    online.value = false;
  }
}

async function post(path: string, body?: unknown) {
  await fetch(`${base.value}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  await refresh();
}

async function startRoom(rid: string) { await post(`/api/rooms/${encodeURIComponent(rid)}/start`); }
async function stopRoom(rid: string) { await post(`/api/rooms/${encodeURIComponent(rid)}/stop`); }
async function startAll() { await post('/api/start_all'); }
async function stopAll() { await post('/api/stop_all'); }

async function delRoom(rid: string) {
  if (!confirm(`删除房间 ${rid} ？`)) return;
  await fetch(`${base.value}/api/rooms/${encodeURIComponent(rid)}`, { method: 'DELETE' });
  await refresh();
}

async function addOne() {
  const v = newRid.value.trim();
  if (!v) return;
  await fetch(`${base.value}/api/rooms/${encodeURIComponent(v)}`, { method: 'POST' });
  newRid.value = '';
  await refresh();
}

function pickCsv() { fileInputRef.value?.click(); }

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const ids = parseRoomIds(await file.text());
  if (ids.length) {
    await fetch(`${base.value}/api/rooms/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids })
    });
    await refresh();
  }
  input.value = '';
}

/** 从 CSV/纯文本里抽取直播号：支持 live.douyin.com/数字、room_num 列、或每行一个数字。 */
function parseRoomIds(text: string): string[] {
  const out = new Set<string>();
  for (const line of text.split(/[\r\n]+/)) {
    for (const cell of line.split(',')) {
      const m = cell.match(/live\.douyin\.com\/(\d+)/) || cell.match(/\b(\d{8,20})\b/);
      if (m) out.add(m[1]);
    }
  }
  return [...out];
}

refresh();
timer = window.setInterval(refresh, 3000);
onBeforeUnmount(() => window.clearInterval(timer));
</script>

<style scoped lang="scss">
.worker-view {
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
  padding: 18px;
  background: #f4f6f5;
  color: #18211d;
}

.wk-header,
.control-band,
.stats-grid,
.log-panel {
  max-width: 1680px;
  margin: 0 auto 14px;
}

.wk-header,
.control-band,
.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.wk-header h1 { margin: 0; font-size: 24px; line-height: 1.2; }
.eyebrow { margin: 0 0 4px; color: #66756d; font-size: 13px; }

.header-actions,
.row-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.file-input { display: none; }

.btn,
.icon-btn {
  border: 1px solid #9eb2a6;
  background: #1f7f52;
  color: #fff;
  border-radius: 6px;
  height: 34px;
  padding: 0 13px;
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.btn:disabled,
.icon-btn:disabled { cursor: not-allowed; opacity: 0.45; }
.btn.secondary { color: #214130; background: #e7eee9; }
.btn.ghost { color: #214130; background: #fff; }
.btn.danger { background: #b54848; border-color: #b54848; }
.icon-btn { min-width: 34px; padding: 0 8px; background: #fff; color: #244033; }
.danger-text { color: #b54848; }

.control-band,
.log-panel {
  border: 1px solid #cfdbd4;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-sizing: border-box;
}

.field { display: flex; flex-direction: column; gap: 5px; min-width: 260px; flex: 1; }
.field.compact { min-width: 160px; max-width: 220px; }
.field span { font-size: 12px; color: #66756d; }
.field input {
  height: 34px;
  border: 1px solid #c3d0c8;
  border-radius: 6px;
  padding: 0 10px;
  color: #17221d;
  background: #fbfcfb;
}

.conn { font-size: 13px; color: #a83c3c; }
.conn.ok { color: #16683f; }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
}
.stat { border: 1px solid #cfdbd4; background: #fff; border-radius: 8px; padding: 12px; }
.stat span { display: block; color: #66756d; font-size: 12px; }
.stat strong { display: block; margin-top: 4px; font-size: 24px; }

.panel-title h2 { margin: 0; font-size: 17px; }
.panel-title span { color: #66756d; font-size: 13px; }

.table-wrap { margin-top: 10px; overflow: auto; max-height: calc(100vh - 300px); }
table { width: 100%; border-collapse: collapse; min-width: 880px; }
th, td {
  text-align: left;
  border-bottom: 1px solid #e5ebe8;
  padding: 9px 8px;
  vertical-align: middle;
  font-size: 13px;
}
th { color: #53645c; font-weight: 600; background: #f7f9f8; position: sticky; top: 0; z-index: 1; }

.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #9aa6a0; }
.dot.on { background: #2ec27e; box-shadow: 0 0 6px #2ec27e; }
.dot.warn { background: #f5a623; box-shadow: 0 0 6px #f5a623; }
.dot.off { background: #9aa6a0; }

.muted { color: #66756d; }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.empty { height: 120px; text-align: center; color: #66756d; }

@media (max-width: 900px) {
  .wk-header,
  .control-band { align-items: stretch; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .stats-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .field,
  .field.compact { width: 100%; min-width: 0; max-width: none; }
}
</style>
