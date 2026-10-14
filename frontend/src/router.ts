import { createRouter, createWebHistory } from 'vue-router'
import { type MessageKey, t } from './lib/i18n'

declare module 'vue-router' {
  interface RouteMeta {
    title?: MessageKey
  }
}

// The public page and the admin are separate chunks: a link recipient doesn't download the
// upload, tus and management code.
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/s/:slug',
      name: 'public-share',
      component: () => import('./public/PublicShareView.vue'),
      props: true,
    },
    {
      path: '/',
      component: () => import('./admin/AdminLayout.vue'),
      children: [
        { path: '', name: 'new', component: () => import('./admin/NewShareView.vue'), meta: { title: 'page.new' } },
        { path: 'shares', name: 'shares', component: () => import('./admin/SharesView.vue'), meta: { title: 'page.shares' } },
        {
          path: 'shares/:slug',
          name: 'share',
          component: () => import('./admin/ShareDetailView.vue'),
          props: true,
          meta: { title: 'page.share' },
        },
        { path: 'users', name: 'users', component: () => import('./admin/UsersView.vue'), meta: { title: 'page.users' } },
      ],
    },
    // Invitation and password reset — before sign-in, without the admin header
    {
      path: '/invite/:token',
      name: 'invite',
      component: () => import('./account/TokenView.vue'),
      props: (route) => ({ token: route.params.token, kind: 'invite' }),
      meta: { title: 'page.invite' },
    },
    {
      path: '/reset/:token',
      name: 'reset',
      component: () => import('./account/TokenView.vue'),
      props: (route) => ({ token: route.params.token, kind: 'reset' }),
      meta: { title: 'page.reset' },
    },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('./NotFoundView.vue') },
  ],
  scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
})

router.afterEach((to) => {
  if (to.meta.title) document.title = `${t(to.meta.title)} — Share`
})
