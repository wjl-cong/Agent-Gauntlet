/**
 * Markdown 渲染工具 —— 评测结论 / 用例答案统一走这里
 * marked 解析 + DOMPurify 消毒，防止 LLM 输出注入脚本
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

export function mdRender(text) {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text))
}
