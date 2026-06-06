import { SentinelAction, SentinelState } from '../sentinelTypes';
import { mockSentinelActions, mockSentinelState } from '../sentinelMockData';

/**
 * Mock API service for Sentinel data
 * Simulates network delay for realistic polling behavior
 * Ready to replace with real HTTP calls later
 */

const NETWORK_DELAY_MS = 200;

function simulateNetworkDelay(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, NETWORK_DELAY_MS));
}

export interface SentinelStateResponse {
  state: SentinelState;
  recentActions: SentinelAction[];
}

/**
 * Fetches current Sentinel state and recent actions
 */
export async function fetchSentinelState(): Promise<SentinelStateResponse> {
  await simulateNetworkDelay();

  return {
    state: {
      ...mockSentinelState,
      lastUpdated: Date.now(),
    },
    recentActions: mockSentinelActions,
  };
}

/**
 * Fetches actions filtered by state type
 */
export async function fetchActionsByState(stateType: string): Promise<SentinelAction[]> {
  await simulateNetworkDelay();

  return mockSentinelActions.filter(action => action.type === stateType);
}
