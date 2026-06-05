import assert from 'node:assert/strict'

import {
  clearPendingUpload,
  getPendingUpload,
  setPendingUpload,
} from '../src/store/pendingUpload.js'

clearPendingUpload()
assert.deepEqual(getPendingUpload(), {
  files: [],
  simulationRequirement: '',
  isPending: false,
})

const files = [
  { name: 'agents.csv', size: 12 },
  { name: 'edges.csv', size: 34 },
]

setPendingUpload(files, 'simulate a launch campaign')

const pending = getPendingUpload()
assert.equal(pending.isPending, true)
assert.equal(pending.simulationRequirement, 'simulate a launch campaign')
assert.deepEqual(pending.files.map(file => file.name), ['agents.csv', 'edges.csv'])
assert.deepEqual(
  pending.files.map(file => file.size),
  files.map(file => file.size),
  'pending upload keeps the caller-selected File list contents intact'
)

clearPendingUpload()
assert.deepEqual(getPendingUpload(), {
  files: [],
  simulationRequirement: '',
  isPending: false,
})
