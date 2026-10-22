import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

test('真实界面：上传 → 参数试验 → 黄金评测 → 发布 → 历史回滚', async ({ page, request }) => {
  const env = fs.readFileSync(path.resolve('../.env'), 'utf8')
  const token = env.match(/^RAGLAB_API_TOKEN=(.+)$/m)![1].trim()
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await page.getByLabel('访问令牌').fill(token)
  await page.getByRole('button', {name: '连接', exact: true}).click()
  await expect(page.getByText('环境已连接', {exact: true})).toBeVisible()
  const name = `浏览器验证-${Date.now()}`
  await page.getByLabel('新知识库名称').fill(name)
  await page.getByRole('button', {name: '＋ 新建知识库'}).click()
  await expect(page.getByLabel('当前知识库')).toContainText(name)
  await page.locator('input[type=file]').first().setInputFiles({name: '工艺规范.txt', mimeType: 'text/plain',
    buffer: Buffer.from('焊接规范\n\n焊接温度保持80摄氏度。作业前必须完成安全检查并佩戴防护装备。')})
  await expect(page.getByText('工艺规范.txt', {exact: true})).toBeVisible()
  await page.getByLabel('窗口长度', {exact: true}).fill('100;200')
  await page.getByLabel('重叠字符').fill('0')
  await page.getByRole('button', {name: '▶ 运行处理试验'}).click()
  await expect(page.getByText('试验完成，共 2 个方案')).toBeVisible({timeout: 120000})
  await expect(page.locator('.chunk-grid article').first()).toBeVisible()
  const kbId = await page.getByLabel('当前知识库').inputValue()
  const docsResponse = await request.get(`http://127.0.0.1:8018/api/v1/knowledge-bases/${kbId}/documents`, {headers: {Authorization: `Bearer ${token}`}})
  const docs = await docsResponse.json()
  const golden = [{id: 'q1', query: '焊接温度是多少', relevant_documents: [docs[0].id],
    evidence: [{document_id: docs[0].id, block_id: 'b1', start: 0, end: 14}]}]
  await page.getByRole('button', {name: '黄金集与评测'}).click()
  await page.getByLabel('黄金集JSON').fill(JSON.stringify(golden))
  await page.getByRole('button', {name: '保存黄金集', exact: true}).click()
  await expect(page.getByText('黄金集版本已固定')).toBeVisible()
  await page.getByRole('button', {name: '运行黄金集评测'}).click()
  await expect(page.getByText('评测完成，逐题结果已保存')).toBeVisible({timeout: 120000})
  await page.getByRole('button', {name: '逐题', exact: true}).first().click()
  await expect(page.getByText('q1 · 焊接温度是多少')).toBeVisible()
  await page.getByLabel('检索问题').fill('焊接温度是多少')
  await page.getByRole('button', {name: '检索', exact: true}).click()
  await expect(page.locator('.result-summary').last()).toContainText('命中')
  await page.getByRole('button', {name: '版本发布', exact: false}).click()
  await page.getByRole('button', {name: '构建并验证', exact: true}).click()
  await expect(page.getByText('完整语料构建与验证通过，可以发布')).toBeVisible({timeout: 120000})
  await page.getByRole('button', {name: '发布此版本', exact: true}).click()
  await expect(page.getByText('活动版本', {exact: true})).toBeVisible()
  // 再建完整候选并发布，然后通过历史卡片回滚。
  await page.getByRole('button', {name: '构建并验证', exact: true}).click()
  await expect(page.getByText('完整语料构建与验证通过，可以发布')).toBeVisible({timeout: 120000})
  await page.getByRole('button', {name: '切换到此版本 / 回滚', exact: true}).and(page.locator(':enabled')).first().click()
  await expect(page.getByText('活动版本已切换；可选择历史版本执行回滚')).toBeVisible()
  const rollback = page.getByRole('button', {name: '切换到此版本 / 回滚', exact: true})
  await expect(rollback.filter({visible: true}).first()).toBeVisible()
  await page.locator('.release-card').filter({has: page.getByText('验证通过', {exact: true})}).getByRole('button', {name: '切换到此版本 / 回滚'}).click()
  await page.screenshot({path: '../test-results/workbench-release.png', fullPage: true})
  await page.getByRole('button', {name: '文件处理试验'}).click()
  await page.screenshot({path: '../test-results/workbench.png', fullPage: true})
  expect(errors).toEqual([])
})
