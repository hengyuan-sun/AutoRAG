<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps<{documentId: string; parser: string; token: string; activeItemUid?: string}>()
const emit = defineEmits<{selectItem: [uid: string]}>()
const manifest = ref<any>(null), items = ref<any[]>([]), selected = ref<any>(null)
const page = ref(1), pageSize = 50, itemType = ref(''), total = ref(0), loading = ref(false), error = ref('')

async function loadItems() {
  if (!props.documentId) return
  loading.value = true; error.value = ''
  try {
    const suffix = itemType.value ? `&type=${encodeURIComponent(itemType.value)}` : ''
    const result = await api(`/documents/${props.documentId}/ir/items?parser=${encodeURIComponent(props.parser)}&page=${page.value}&page_size=${pageSize}${suffix}`, props.token)
    items.value = result.items; total.value = result.total
    if (props.activeItemUid) selected.value = result.items.find((item: any) => item.uid === props.activeItemUid) || selected.value
  } catch (e: any) { error.value = e.message || 'IR条目加载失败' }
  finally { loading.value = false }
}

async function load() {
  if (!props.documentId) return
  manifest.value = null; selected.value = null; page.value = 1
  loading.value = true; error.value = ''
  try {
    manifest.value = await api(`/documents/${props.documentId}/ir?parser=${encodeURIComponent(props.parser)}`, props.token)
    await loadItems()
    if (props.activeItemUid) {
      const found = items.value.find(item => item.uid === props.activeItemUid)
      if (found) selected.value = found
      else await locateItem(props.activeItemUid)
    }
  } catch (e: any) { error.value = e.message || 'DocumentIR加载失败' }
  finally { loading.value = false }
}

async function selectItem(item: any) {
  selected.value = item
  emit('selectItem', item.uid)
  try {
    const detail = await api(`/documents/${props.documentId}/ir/items/${encodeURIComponent(item.uid)}?parser=${encodeURIComponent(props.parser)}`, props.token)
    selected.value = {...detail.item, relations: detail.relations}
  } catch (e: any) { error.value = e.message || 'IR条目详情加载失败' }
}

async function locateItem(uid: string) {
  if (!manifest.value || !uid) return
  if (itemType.value) { itemType.value = ''; await nextTick() }
  const pages = Math.ceil(manifest.value.item_count / pageSize)
  for (let candidate = 1; candidate <= pages; candidate++) {
    page.value = candidate
    await loadItems()
    const item = items.value.find(row => row.uid === uid)
    if (item) { await selectItem(item); return }
  }
  error.value = `IR条目 ${uid} 不在当前文档快照中`
}

watch(() => [props.documentId, props.parser], load, {immediate: true})
watch(() => props.activeItemUid, async uid => {
  if (!uid) return
  const found = items.value.find(item => item.uid === uid)
  if (found) await selectItem(found)
  else await locateItem(uid)
})
watch(itemType, async () => { page.value = 1; await loadItems() })
</script>

<template>
  <section class="panel ir-viewer" aria-label="DocumentIR浏览器">
    <div class="panel-heading"><h2>DocumentIR结构浏览</h2><span v-if="manifest" class="badge">Schema {{manifest.schema_version}} · {{manifest.item_count}} 项</span></div>
    <p v-if="manifest" class="subtle">解析器 {{manifest.parser_identity}} · {{manifest.page_count}} 页 · SHA-256 {{manifest.ir_sha256}}</p>
    <div v-if="manifest" class="inline ir-controls">
      <label>条目类型<select v-model="itemType" aria-label="IR条目类型"><option value="">全部类型</option><option v-for="type in Object.keys(manifest.item_counts)" :key="type" :value="type">{{type}} · {{manifest.item_counts[type]}}</option></select></label>
      <button :disabled="loading || page <= 1" @click="page--; loadItems()">上一页</button>
      <span>第 {{page}} 页 / {{Math.max(1, Math.ceil(total / pageSize))}}</span>
      <button :disabled="loading || page * pageSize >= total" @click="page++; loadItems()">下一页</button>
    </div>
    <p v-if="error" role="alert" class="warning">{{error}}</p>
    <p v-if="manifest?.warnings?.length" class="warning">{{manifest.warnings.join('；')}}</p>
    <div class="ir-browser">
      <div class="ir-item-list" aria-label="IR条目列表">
        <button v-for="item in items" :key="item.uid" class="ir-item" :class="{selected: item.uid === selected?.uid, linked: item.uid === activeItemUid}" @click="selectItem(item)">
          <span>{{item.type}}</span><b>{{item.text || item.title || item.table_markdown || item.uid}}</b><small>{{item.uid}} · {{item.provenance?.page ? `第${item.provenance.page}页` : '无页码'}}</small>
        </button>
        <p v-if="!items.length && !loading" class="empty">没有符合条件的IR条目。</p>
      </div>
      <article v-if="selected" class="ir-item-detail">
        <div class="chunk-meta">{{selected.type}} · {{selected.uid}} · {{selected.status || '未标注状态'}}</div>
        <pre>{{selected.text || selected.table_markdown || selected.title || JSON.stringify(selected, null, 2)}}</pre>
        <h3>来源定位与解析属性</h3><pre>{{JSON.stringify({provenance: selected.provenance, cells: selected.cells, relations: selected.relations}, null, 2)}}</pre>
      </article>
      <p v-else class="empty">选择左侧条目查看完整字段和来源定位。</p>
    </div>
  </section>
</template>
