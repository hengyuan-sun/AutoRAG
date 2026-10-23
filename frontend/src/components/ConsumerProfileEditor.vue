<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { fieldPreviewRows, isSupportedSelector } from '../consumerProfiles'

type ProfileField = {key: string; selector: string; aliases: string[]; item_types: string[]; cardinality: 'one'|'many'; transform: string; required: boolean}
const props = defineProps<{documentId: string; parser: string; token: string}>()
const profiles = ref<any[]>([]), profileId = ref(''), profileName = ref('自定义消费字段')
const fields = ref<ProfileField[]>([]), preview = ref<any>(null), error = ref(''), busy = ref(false), creating = ref(false)
const fieldKey = ref(''), selector = ref('items[*].text'), aliases = ref(''), itemTypes = ref('paragraph'),
  cardinality = ref<'one'|'many'>('many'), transform = ref('identity'), required = ref(false)
const chosen = computed(() => profiles.value.find(profile => profile.id === profileId.value))
const selectorExamples = ['meta.filename', 'outline[*].title', 'items[*].text', 'items[*].provenance.page', 'items[*].cells[*].text']

async function loadProfiles() {
  error.value = ''
  try {
    profiles.value = await api('/consumer-profiles', props.token)
    if (!profileId.value && !creating.value && profiles.value.length) selectProfile(profiles.value[0].id)
  } catch (e: any) { error.value = e.message || 'Profile加载失败' }
}
function selectProfile(id: string) {
  if (!id) { newProfile(); return }
  creating.value = false
  profileId.value = id; preview.value = null
  const profile = profiles.value.find(row => row.id === id)
  if (profile) { profileName.value = profile.name; fields.value = structuredClone(profile.fields) }
}
function newProfile() { creating.value = true; profileId.value = ''; profileName.value = '自定义消费字段'; fields.value = []; preview.value = null }
function addField() {
  const key = fieldKey.value.trim()
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(key)) { error.value = '字段key使用英文、数字和下划线，且以字母开头'; return }
  if (!isSupportedSelector(selector.value)) { error.value = '字段路径不在支持列表中'; return }
  if (fields.value.some(field => field.key === key)) { error.value = '字段key不能重复'; return }
  const selectedTypes = itemTypes.value.split(',').map(value => value.trim()).filter(Boolean)
  fields.value.push({key, selector: selector.value.trim(), aliases: aliases.value.split(',').map(v => v.trim()).filter(Boolean),
    item_types: selectedTypes, cardinality: cardinality.value, transform: transform.value, required: required.value})
  fieldKey.value = ''; aliases.value = ''; required.value = false; error.value = ''; preview.value = null
}
function removeField(key: string) { fields.value = fields.value.filter(field => field.key !== key); preview.value = null }
async function saveProfile() {
  if (!profileName.value.trim() || !fields.value.length) { error.value = '请填写名称并至少配置一个字段'; return }
  busy.value = true; error.value = ''
  try {
    const saved = await api('/consumer-profiles', props.token, {method: 'POST', body: JSON.stringify({
      ...(profileId.value ? {id: profileId.value} : {}), name: profileName.value, fields: fields.value})})
    await loadProfiles(); selectProfile(saved.id)
    preview.value = null
  } catch (e: any) { error.value = e.message || 'Profile保存失败' }
  finally { busy.value = false }
}
async function runPreview() {
  if (!chosen.value) { error.value = '先保存字段配置，再运行预览'; return }
  busy.value = true; error.value = ''
  try {
    preview.value = await api(`/documents/${props.documentId}/consumer-preview?parser=${encodeURIComponent(props.parser)}`,
      props.token, {method: 'POST', body: JSON.stringify({profile_id: chosen.value.id, version: chosen.value.version})})
  } catch (e: any) { error.value = e.message || '预览失败' }
  finally { busy.value = false }
}
watch(() => [props.documentId, props.parser], () => { preview.value = null })
onMounted(loadProfiles)
</script>

<template>
  <section class="panel consumer-editor" aria-label="消费字段Profile编辑器">
    <div class="panel-heading"><h2>业务消费字段配置</h2><span v-if="chosen" class="badge">v{{chosen.version}} · {{chosen.content_hash.slice(0, 12)}}</span></div>
    <div class="inline profile-select-row">
      <label>消费Profile<select v-model="profileId" aria-label="消费Profile" @change="selectProfile(profileId)"><option value="">新建Profile</option><option v-for="profile in profiles" :key="profile.id" :value="profile.id">{{profile.name}} · v{{profile.version}}</option></select></label>
      <button @click="newProfile">新建</button>
    </div>
    <label>Profile名称<input v-model="profileName" aria-label="Profile名称" maxlength="100"></label>
    <div class="profile-field-form">
      <label>输出字段key<input v-model="fieldKey" aria-label="输出字段key" placeholder="例如 process_text"></label>
      <label>IR字段路径<input v-model="selector" aria-label="IR字段路径" list="ir-selector-examples"><datalist id="ir-selector-examples"><option v-for="path in selectorExamples" :value="path"></option></datalist></label>
      <label>条目类型<input v-model="itemTypes" aria-label="Profile条目类型" placeholder="paragraph,table"></label>
      <label>别名<input v-model="aliases" aria-label="字段别名" placeholder="process,weld_no"></label>
      <label>基数<select v-model="cardinality" aria-label="字段基数"><option value="many">多个值</option><option value="one">单个值</option></select></label>
      <label>转换<select v-model="transform" aria-label="字段转换"><option value="identity">原值</option><option value="join_text">拼接文本</option><option value="table_markdown">表格Markdown</option></select></label>
      <label class="profile-required"><input v-model="required" type="checkbox" aria-label="必填字段">必填</label>
      <button @click="addField">添加字段</button>
    </div>
    <ul class="profile-field-list"><li v-for="field in fields" :key="field.key"><div><b>{{field.key}}</b><small>{{field.aliases.join(', ') || '无别名'}} · {{field.selector}} · {{field.item_types.join(', ') || '全部类型'}}</small></div><button class="quiet" :aria-label="`删除字段 ${field.key}`" @click="removeField(field.key)">删除</button></li></ul>
    <p v-if="error" role="alert" class="warning">{{error}}</p>
    <div class="inline"><button class="primary" :disabled="busy" @click="saveProfile">{{profileId ? '保存为新版本' : '创建Profile'}}</button><button :disabled="busy || !profileId" @click="runPreview">预览消费结果</button></div>
    <section v-if="preview" class="profile-preview" aria-label="消费字段预览"><div class="panel-heading"><h3>解析对象预览 · v{{preview.profile_version}}</h3><span class="subtle">IR {{preview.ir_sha256.slice(0, 12)}}</span></div><p v-if="preview.missing_required.length" class="warning">缺少必填字段：{{preview.missing_required.join('、')}}</p><article v-for="(field, key) in preview.fields" :key="key" class="profile-preview-field"><div class="chunk-meta"><b>{{key}}</b><span>{{field.status}} · {{field.selector}}</span></div><div v-for="row in fieldPreviewRows(field)" :key="`${row.source_uid}-${JSON.stringify(row.value)}`" class="profile-value"><pre>{{JSON.stringify(row.value, null, 2)}}</pre><small>来源 {{row.source_uid || '文档元信息'}} · {{row.locationText}}</small></div><p v-if="!field.values.length" class="subtle">当前解析结果没有该字段。</p></article></section>
  </section>
</template>
