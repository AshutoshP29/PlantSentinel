import { useSyncExternalStore } from 'react'

// Tiny pub/sub so screens refresh when shared data changes
// (a new document, a new audit row, a blocked attempt).
export type Topic = 'documents' | 'audit' | 'blocked' | 'ingest' | 'users'

const versions = new Map<Topic, number>()
const listeners = new Map<Topic, Set<() => void>>()

export function emit(topic: Topic): void {
  versions.set(topic, (versions.get(topic) ?? 0) + 1)
  listeners.get(topic)?.forEach((fn) => fn())
}

function subscribe(topic: Topic, fn: () => void): () => void {
  if (!listeners.has(topic)) listeners.set(topic, new Set())
  listeners.get(topic)!.add(fn)
  return () => listeners.get(topic)!.delete(fn)
}

/** A number that changes whenever `topic` is emitted; use it as a refetch dependency. */
export function useTopicVersion(topic: Topic): number {
  return useSyncExternalStore(
    (fn) => subscribe(topic, fn),
    () => versions.get(topic) ?? 0,
  )
}
