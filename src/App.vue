<template>
  <el-container class="app-container">
    <!-- 顶部导航栏 -->
    <el-header class="app-navbar">
      <div class="navbar-content">
        <!-- 左侧 Logo -->
        <div class="navbar-left">
          <el-icon :size="20" class="logo-icon">
            <Grid />
          </el-icon>
          <span class="logo-text">Double-Layer HotStuff</span>
        </div>
        
        <!-- 右侧工具栏 -->
        <div class="navbar-right">
          <el-space :size="16">
            <el-link 
              href="https://github.com" 
              target="_blank" 
              :underline="false"
              class="navbar-link"
            >
              <el-icon><Link /></el-icon>
              <span>GitHub</span>
            </el-link>
            <el-link 
              href="#" 
              :underline="false"
              class="navbar-link"
            >
              <el-icon><Document /></el-icon>
              <span>Docs</span>
            </el-link>
          </el-space>
        </div>
      </div>
    </el-header>
    
    <!-- 主内容区域 -->
    <el-main class="app-main">
      <div class="main-wrapper">
        <router-view v-slot="{ Component }">
          <transition name="fade-transform" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </el-main>
  </el-container>
</template>

<script>
import { Grid, Link, Document } from '@element-plus/icons-vue'

export default {
  name: 'App',
  components: {
    Grid,
    Link,
    Document
  }
}
</script>

<style>
/* ========== 全局样式重置 ========== */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body {
  width: 100%;
  height: 100%;
  overflow-x: hidden;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', 
               Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Arial, sans-serif;
  background-color: #f0f2f5;
  color: #2c3e50;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 代码/日志强制等宽字体 */
code,
pre,
.code-block,
.log-content,
.message-log {
  font-family: 'JetBrains Mono', 'Fira Code', 'Roboto Mono', 'Courier New', Consolas, monospace !important;
  font-size: 13px;
  line-height: 1.6;
}

#app {
  width: 100%;
  height: 100%;
  min-height: 100vh;
}

/* ========== 全局滚动条美化 ========== */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
  transition: background 0.3s;
}

::-webkit-scrollbar-thumb:hover {
  background: #b0b0b0;
}

/* ========== Element Plus 全局样式覆盖 ========== */
.el-button {
  font-weight: 500;
}

.el-card {
  border-radius: 4px;
}
</style>

<style scoped>
/* ========== 应用容器 ========== */
.app-container {
  min-height: 100vh;
  background-color: #f0f2f5;
  flex-direction: column;
}

/* ========== 顶部导航栏 ========== */
.app-navbar {
  height: 48px !important;
  background: linear-gradient(135deg, #001529 0%, #002140 100%);
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  padding: 0;
  line-height: 48px;
  position: sticky;
  top: 0;
  z-index: 999;
}

.navbar-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  padding: 0 20px;
  max-width: 1920px;
  margin: 0 auto;
}

/* 左侧 Logo */
.navbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 100%;
}

.logo-icon {
  color: #1890ff;
  filter: drop-shadow(0 0 6px rgba(24, 144, 255, 0.4));
}

.logo-text {
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.3px;
  user-select: none;
}

/* 右侧工具栏 */
.navbar-right {
  display: flex;
  align-items: center;
  height: 100%;
}

.navbar-link {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  color: rgba(255, 255, 255, 0.85) !important;
  font-size: 14px;
  font-weight: 500;
  border-radius: 4px;
  transition: all 0.3s;
}

.navbar-link:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff !important;
}

.navbar-link .el-icon {
  font-size: 16px;
}

/* ========== 主内容区域 ========== */
.app-main {
  flex: 1;
  padding: 16px;
  background-color: #f0f2f5;
  overflow-y: auto;
  overflow-x: hidden;
}

.main-wrapper {
  max-width: 1920px;
  margin: 0 auto;
  width: 100%;
}

/* ========== 路由过渡动画 (Vben 风格) ========== */
.fade-transform-enter-active,
.fade-transform-leave-active {
  transition: all 0.28s ease-out;
}

.fade-transform-enter-from {
  opacity: 0;
  transform: translateX(-30px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateX(30px);
}

/* ========== 响应式设计 ========== */
@media (max-width: 768px) {
  .navbar-content {
    padding: 0 12px;
  }
  
  .logo-text {
    font-size: 14px;
  }
  
  .navbar-link span {
    display: none;
  }
  
  .navbar-link {
    padding: 6px 8px;
  }
  
  .app-main {
    padding: 12px;
  }
}

@media (max-width: 480px) {
  .logo-icon {
    font-size: 18px !important;
  }
  
  .logo-text {
    display: none;
  }
}
</style>
