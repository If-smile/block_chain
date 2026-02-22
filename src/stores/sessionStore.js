import { defineStore } from 'pinia'

/**
 * Pinia store for consensus session state.
 * Decouples session/phase/connected-nodes state from HomePage and NodePage.
 */
export const useSessionStore = defineStore('session', {
  state: () => ({
    sessionId: null,
    sessionConfig: null,
    connectedNodes: [],
    consensusStatus: null,
    currentPhase: null,
    currentView: 0,
    leaderId: 0,
    createdAt: null
  }),

  getters: {
    /** Session info shape used by HomePage (sessionId + config + status + createdAt). */
    sessionInfo(state) {
      if (!state.sessionId) return null
      return {
        sessionId: state.sessionId,
        config: state.sessionConfig,
        status: state.consensusStatus,
        currentView: state.currentView,
        leaderId: state.leaderId,
        createdAt: state.createdAt
      }
    },

    hasSession(state) {
      return !!state.sessionId
    }
  },

  actions: {
    /**
     * Set session after create-session API success.
     * @param {Object} data - API response: { sessionId, config, status?, createdAt? }
     */
    setSession(data) {
      if (!data) return
      this.sessionId = data.sessionId ?? null
      this.sessionConfig = data.config ?? null
      this.consensusStatus = data.status ?? 'waiting'
      this.createdAt = data.createdAt ?? null
      this.currentView = data.currentView ?? 0
      this.leaderId = data.leaderId ?? 0
      this.currentPhase = null
      this.connectedNodes = []
    },

    /**
     * Update connected nodes list (from socket or API).
     * @param {number[]} nodes - List of node IDs
     */
    updateConnectedNodes(nodes) {
      this.connectedNodes = Array.isArray(nodes) ? [...nodes] : []
    },

    /**
     * Update consensus phase (from socket phase_update / new_round).
     * @param {Object} payload - { phase?, step?, leader?, view? }
     */
    updatePhase(payload) {
      if (!payload) return
      if (payload.phase !== undefined) this.currentPhase = payload.phase
      if (payload.leader !== undefined) this.leaderId = payload.leader
      if (payload.view !== undefined) this.currentView = payload.view
    },

    /**
     * Update consensus status (e.g. running, completed).
     * @param {string} status
     */
    updateConsensusStatus(status) {
      this.consensusStatus = status
    },

    /**
     * Reset store to initial state (e.g. when resetting form).
     */
    resetStore() {
      this.sessionId = null
      this.sessionConfig = null
      this.connectedNodes = []
      this.consensusStatus = null
      this.currentPhase = null
      this.currentView = 0
      this.leaderId = 0
      this.createdAt = null
    }
  }
})
