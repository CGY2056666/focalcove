package com.focuscompass.app.capture

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureStateStoreTest {
    @After
    fun cleanUp() {
        CaptureStateStore.reset()
    }

    @Test
    fun `near black frames stay a capture health signal and never become distraction`() {
        CaptureStateStore.started("session-1", 600)
        CaptureStateStore.uploaded(
            CaptureFrameResult(
                classification = "focused",
                rollingSummary = "仍在目标内",
            ),
        )

        CaptureStateStore.nearBlack(
            NearBlackSignalUpdate(
                state = NearBlackSignalState.SUSPECTED,
                event = NearBlackSignalEvent.SUSPECTED,
                consecutiveNearBlackFrames = 1,
            ),
        )
        val suspected = CaptureStateStore.state.value
        assertEquals(CapturePhase.CAPTURING, suspected.phase)
        assertEquals("focused", suspected.classification)
        assertEquals(1, suspected.skippedFrames)
        assertEquals(1, suspected.totalNearBlackFrames)
        assertNull(suspected.captureHealthWarning)

        CaptureStateStore.nearBlack(
            NearBlackSignalUpdate(
                state = NearBlackSignalState.CONFIRMED,
                event = NearBlackSignalEvent.CONFIRMED,
                consecutiveNearBlackFrames = 2,
            ),
        )
        val confirmed = CaptureStateStore.state.value
        assertEquals(CapturePhase.CAPTURING, confirmed.phase)
        assertEquals("focused", confirmed.classification)
        assertEquals(2, confirmed.skippedFrames)
        assertEquals(2, confirmed.totalNearBlackFrames)
        assertEquals(2, confirmed.captureHealthWarning?.consecutiveNearBlackFrames)
        assertTrue(confirmed.captureHealthWarning?.message?.contains("投屏") == true)
    }

    @Test
    fun `usable frame clears warning without losing session counters`() {
        CaptureStateStore.started("session-2", 300)
        CaptureStateStore.nearBlack(
            NearBlackSignalUpdate(
                state = NearBlackSignalState.CONFIRMED,
                event = NearBlackSignalEvent.CONFIRMED,
                consecutiveNearBlackFrames = 2,
            ),
        )

        CaptureStateStore.captureRecovered()

        val state = CaptureStateStore.state.value
        assertEquals(CapturePhase.CAPTURING, state.phase)
        assertEquals("session-2", state.sessionId)
        assertEquals(1, state.skippedFrames)
        assertEquals(1, state.totalNearBlackFrames)
        assertNull(state.captureHealthWarning)
    }

    @Test
    fun `reauthorization problem preserves the active session and timer`() {
        CaptureStateStore.started("session-3", 240)
        CaptureStateStore.uploaded(CaptureFrameResult(classification = "uncertain"))
        CaptureStateStore.tick(222)

        CaptureStateStore.captureProblem("需要重新授权整屏共享")

        val state = CaptureStateStore.state.value
        assertEquals(CapturePhase.CAPTURING, state.phase)
        assertEquals("session-3", state.sessionId)
        assertEquals(222, state.remainingSeconds)
        assertEquals(1, state.uploadedFrames)
        assertEquals("uncertain", state.classification)
        assertEquals("需要重新授权整屏共享", state.captureHealthWarning?.message)
    }

    @Test
    fun `parallel capture updates do not lose skipped frame counts`() {
        CaptureStateStore.started("session-4", 120)
        val workers = 8
        val updatesPerWorker = 100
        val start = CountDownLatch(1)
        val done = CountDownLatch(workers)
        val executor = Executors.newFixedThreadPool(workers)
        repeat(workers) {
            executor.execute {
                start.await()
                repeat(updatesPerWorker) { CaptureStateStore.skipped() }
                done.countDown()
            }
        }

        start.countDown()
        assertTrue(done.await(5, TimeUnit.SECONDS))
        executor.shutdownNow()

        assertEquals(workers * updatesPerWorker, CaptureStateStore.state.value.skippedFrames)
        assertEquals(CapturePhase.CAPTURING, CaptureStateStore.state.value.phase)
    }
}
