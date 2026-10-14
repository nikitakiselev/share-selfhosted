import { createApp } from 'vue'
import App from './App.vue'
import { getLocale } from './lib/i18n'
import { router } from './router'
import './style.css'

document.documentElement.lang = getLocale()

createApp(App).use(router).mount('#app')
