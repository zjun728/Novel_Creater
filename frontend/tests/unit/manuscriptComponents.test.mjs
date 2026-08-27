import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('chapter list is an ordered volume directory with sibling reader and download controls', async () => {
  const source = await readFile(new URL('../../src/components/manuscript/ManuscriptChapterList.vue', import.meta.url), 'utf8')
  assert.match(source, /<section[^>]*v-for="\(volume, volumeIndex\) in volumes"/)
  assert.match(source, /<ol[^>]*class="manuscript-chapter-list__chapters"/)
  assert.match(source, /<li[^>]*v-for="chapter in volume\.chapters"/)
  assert.match(source, /<router-link[\s\S]*class="manuscript-chapter-list__reader"/)
  assert.match(source, /<button[^>]*class="manuscript-chapter-list__download"/)
  assert.match(source, /<time[^>]*:datetime=/)
  assert.match(source, /<\/router-link>\s*<button/)
})
