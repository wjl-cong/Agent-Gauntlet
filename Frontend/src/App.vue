<script setup>
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="shell">
    <header class="topbar glass-panel">
      <div class="brand">
        <img src="/favicon.svg" alt="logo" class="brand-logo" />
        <span class="brand-name metal-text">AGENTGAUNTLET</span>
        <span class="brand-sub">Agent 红队评测平台</span>
      </div>
      <nav class="nav">
        <RouterLink to="/" class="nav-link">Agent 对话</RouterLink>
        <RouterLink to="/tasks" class="nav-link">测试中心</RouterLink>
        <RouterLink to="/history" class="nav-link">测试历史</RouterLink>
        <RouterLink to="/apis" class="nav-link">API 测试规划</RouterLink>
      </nav>
    </header>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 16px 24px 0;
  padding: 12px 22px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 26px;
  height: 26px;
  filter: drop-shadow(0 0 6px rgba(56, 242, 216, 0.5));
}

.brand-name {
  font-size: 17px;
  font-weight: 700;
}

.brand-sub {
  font-size: 12px;
  color: var(--g-text-dim);
  padding-left: 12px;
  border-left: 1px solid var(--g-border);
}

.nav {
  display: flex;
  gap: 8px;
}

.nav-link {
  padding: 6px 16px;
  border-radius: 10px;
  color: var(--g-text-dim);
  text-decoration: none;
  font-size: 14px;
  transition: all 0.25s ease;
}

.nav-link:hover {
  color: var(--g-text);
  background: var(--g-panel-strong);
}

.nav-link.router-link-active {
  color: var(--g-accent);
  background: rgba(56, 242, 216, 0.08);
  border: 1px solid var(--g-border-glow);
  box-shadow: 0 0 12px rgba(56, 242, 216, 0.15);
}

.content {
  flex: 1;
  padding: 20px 24px 28px;
  overflow: auto;
}
</style>
