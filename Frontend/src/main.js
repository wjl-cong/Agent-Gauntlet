/**
 * AgentGauntlet 前端入口 — 注册全局插件并挂载根组件
 * 栈与焰哨同源：Vue3 + Pinia + Vue Router + Element Plus（中文语言包）
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import '@/style/main.scss'
import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
