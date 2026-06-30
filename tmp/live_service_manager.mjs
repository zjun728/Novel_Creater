import { pathToFileURL } from 'node:url'
import { runLiveServiceManagerCli } from './live-qa/services/live-service-manager.mjs'

export {
  buildCleanupPlan,
  cleanupServices,
  createServiceRecord,
  evaluateProcessForCleanup,
  readManifest,
  runLiveServiceManagerCli,
  startServices
} from './live-qa/services/live-service-manager.mjs'

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  runLiveServiceManagerCli(process.argv)
}
