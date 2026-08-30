import assert from 'node:assert/strict'
import test from 'node:test'
import { createMemoryHistory, createRouter } from 'vue-router'

import { createProductShellModel } from '../../src/components/layout/productShell.js'
import { projectRoutes } from '../../src/router/projectRoutes.js'


test('all topic routes share one real view and survive browser history', async () => {
  const topicRoutes = projectRoutes.filter(route => String(route.name).startsWith('Topic'))
  assert.deepEqual(topicRoutes.map(route => [route.name, route.props.activeSection]), [
    ['TopicMarket', 'market'],
    ['TopicDiscussions', 'discussions'],
    ['TopicDirections', 'directions'],
    ['TopicCandidates', 'candidates'],
  ])
  assert.equal(new Set(topicRoutes.map(route => route.component)).size, 1)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: projectRoutes.map(route => (
      String(route.name).startsWith('Topic')
        ? { ...route, component: { render: () => null } }
        : route
    )),
  })
  await router.push('/topics/market')
  await router.isReady()
  await router.push('/topics/discussions')
  router.back()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(router.currentRoute.value.name, 'TopicMarket')
})


test('topic center stays selected and gives each section a truthful title', () => {
  for (const [name, title] of [
    ['TopicMarket', '市场发现'],
    ['TopicDiscussions', '选题讨论'],
    ['TopicDirections', '方向库'],
    ['TopicCandidates', '候选种子库'],
  ]) {
    const shell = createProductShellModel({ route: { name, params: {} } })
    assert.equal(shell.globalNavigation[0].label, '选题中心')
    assert.equal(shell.globalNavigation[0].selected, true)
    assert.equal(shell.routeTitle, title)
  }
})
