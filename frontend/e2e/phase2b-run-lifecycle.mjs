function requireHandler(name, handler) {
  if (typeof handler !== 'function') {
    throw new TypeError(`Phase 2B lifecycle requires ${name}`)
  }
  return handler
}


export async function runPhase2BLifecycle({
  body,
  stopServer,
  releaseReservation,
  dropDatabase,
  removeRoot,
}) {
  const runBody = requireHandler('body', body)
  const stop = requireHandler('stopServer', stopServer)
  const release = requireHandler('releaseReservation', releaseReservation)
  const drop = requireHandler('dropDatabase', dropDatabase)
  const remove = requireHandler('removeRoot', removeRoot)
  const servers = []
  const reservations = []
  const releasedReservations = new Set()
  let database
  let root
  let result
  const errors = []

  const lifecycle = Object.freeze({
    registerServer(server) {
      servers.push(server)
      return server
    },
    registerReservation(reservation) {
      reservations.push(reservation)
      return reservation
    },
    setDatabase(value) {
      database = value
      return value
    },
    setRoot(value) {
      root = value
      return value
    },
    async releaseReservation(reservation) {
      if (releasedReservations.has(reservation)) return
      await release(reservation)
      releasedReservations.add(reservation)
    },
  })

  try {
    result = await runBody(lifecycle)
  } catch (error) {
    errors.push(error)
  }

  for (const server of [...servers].reverse()) {
    try {
      await stop(server)
    } catch (error) {
      errors.push(error)
    }
  }
  for (const reservation of reservations) {
    try {
      await lifecycle.releaseReservation(reservation)
    } catch (error) {
      errors.push(error)
    }
  }
  if (database !== undefined) {
    try {
      await drop(database)
    } catch (error) {
      errors.push(error)
    }
  }
  if (root !== undefined) {
    try {
      await remove(root)
    } catch (error) {
      errors.push(error)
    }
  }

  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'Phase 2B body and cleanup failed')
  }
  return result
}
