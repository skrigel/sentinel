# Interactive State Graph with Weave Trace Integration

## Context

The current Sentinel Status page shows a linear timeline of actions, but users need:
1. **Visual workflow understanding** - See Sentinel's state machine (detecting → analyzing → proposing → applying → verifying → completed) as it transitions through states
2. **Trace auditing capability** - Click on any action to view the detailed Weave execution trace that explains *why* and *how* Sentinel made decisions
3. **Live monitoring** - Watch Sentinel work in near-real-time as it detects issues and applies fixes

This enhancement transforms the static timeline into an interactive monitoring surface where users can audit Sentinel's reasoning by drilling into Weave traces for each intervention.

## Design Overview

### Two-Tier Visualization

**Top Section: State Machine Graph**
- Horizontal flow diagram showing Sentinel's current workflow state
- Nodes: detecting → analyzing → proposing → applying → verifying → completed
- Active node highlighted with pulse animation
- Transitions shown as arrows with timing metadata
- Click node to filter timeline to actions in that state

**Bottom Section: Enhanced Timeline with Trace Integration**
- Upgraded ActionTimeline with Weave trace links
- Each action card has "View trace in Weave" button
- Clicking action opens Weave UI in new tab with trace ID
- External link icon indicates new tab behavior
- Trace URL format: `https://weave.wandb.ai/traces/{traceId}` (mock URL for demo)

### Live Updates via Polling

- Poll Sentinel API every 3 seconds for state updates
- Smooth transitions when new actions appear
- Visual indicator when updates are being fetched
- Optimistic UI updates (don't flash/jump content)

### Mock Weave Integration

- Create realistic Weave trace/span data matching W&B Weave schema
- Each SentinelAction links to a trace ID
- Mock spans include: operation name, start/end time, attributes, parent/child relationships
- Demonstrate correlation between spans and metric trajectories

## Critical Files to Modify

### New Components

**1. `/src/app/components/StateMachineGraph.tsx`**
- Renders horizontal state flow diagram
- Props: currentState, stateHistory (with transition timestamps)
- Uses SVG or React-Flow for node/edge rendering
- Interactive: click node → filters timeline
- Animations: pulse on active state, fade completed states

**2. `/src/app/components/EnhancedActionTimeline.tsx`**
- Extends existing ActionTimeline component
- Adds "View trace in Weave" link button to each action
- Click action → opens Weave UI in new tab
- Generates Weave trace URL from traceId
- External link icon next to button text
- Maintains minimalist design aesthetic

**3. `/src/app/hooks/usePolling.ts`**
- Custom React hook for polling data
- Parameters: fetchFn, interval (default 3000ms)
- Returns: { data, isLoading, error, lastUpdated }
- Handles cleanup on unmount
- Pauses polling when page not visible (Page Visibility API)

**4. `/src/app/utils/weaveLinks.ts`**
- Utility functions for generating Weave trace URLs
- `getWeaveTraceUrl(traceId: string): string` - generates mock Weave URL
- Format: `https://weave.wandb.ai/traces/{traceId}`
- Ready to swap for real Weave URL pattern later

### Updated Components

**5. `/src/app/pages/SentinelStatus.tsx`**
- Replace ActionTimeline with EnhancedActionTimeline
- Add StateMachineGraph at top of right column
- Implement usePolling hook to fetch Sentinel state
- Add "Last updated" timestamp indicator
- Grid layout: State graph above timeline

### New Data Models

**6. `/src/app/types/weave.ts`**
- TypeScript interfaces matching Weave schema:
  - `WeaveTrace` - trace metadata, root span ID
  - `WeaveSpan` - span ID, operation, start/end, parent, attributes
  - `SpanAttribute` - key-value pairs (e.g., `history_len: 1200`)
- Reference W&B Weave documentation for accurate schema

**7. `/src/app/sentinelTypes.ts` (update)**
- Add `traceId?: string` to `SentinelAction` interface
- Add `SentinelState` type: currentState, transitions[], activeAgent
- Add `StateTransition` interface: fromState, toState, timestamp, triggeredBy

### Mock Data

**8. `/src/app/mockData/weaveTraces.ts`**
- Mock Weave traces for each intervention
- Example traces:
  - Memory leak detection: spans showing unbounded history growth
  - Event loop stall: spans with high self-time in file I/O
- Correlate span timing with metric spike timestamps
- Include realistic attributes: `history_len`, `rss_mb`, `loop_lag_ms`

**9. `/src/app/sentinelMockData.ts` (update)**
- Add `traceId` to each action linking to mock Weave trace
- Add `mockSentinelState` with current state machine position
- Add state transition history

### API Layer (Mock)

**10. `/src/app/services/sentinelApi.ts`**
- Mock API service simulating real backend
- `fetchSentinelState()` - returns current state + recent actions
- `fetchWeaveTrace(traceId)` - returns mock trace data
- Simulate network delay (100-300ms) for realistic polling
- Ready to swap for real API calls later

## Implementation Details

### State Machine Graph Visualization

**Option A: Custom SVG** (Recommended - matches minimalist aesthetic)
- Hand-coded SVG with Tailwind styling
- Horizontal row of circles (nodes) connected by lines (edges)
- Active node: larger, pulsing, darker color
- Past nodes: green with checkmark
- Future nodes: gray outline
- Lightweight, full control over styling

**Option B: React-Flow**
- Install: `pnpm add reactflow`
- Pre-built node/edge rendering
- More powerful but heavier dependency
- May not match minimalist design without heavy customization

**Recommendation: Start with custom SVG** for design consistency

### Weave Trace Link Integration

**Link Button Design:**
- Appears on each action card in timeline
- Text: "View trace in Weave →" with external link icon
- Styled as subtle text link (blue-600, hover:blue-700)
- Opens in new tab (`target="_blank" rel="noopener noreferrer"`)
- Disabled state when traceId is missing

**URL Generation:**
```typescript
function getWeaveTraceUrl(traceId: string): string {
  // Mock URL for demo - replace with real Weave domain later
  return `https://weave.wandb.ai/traces/${traceId}`;
}
```

**User Experience:**
- Click link → new tab opens with Weave UI showing full trace
- User can audit trace details in Weave's native interface
- Return to Sentinel tab to continue monitoring
- No context switching within Sentinel page

### Polling Mechanism

**usePolling Hook:**
```typescript
function usePolling<T>(
  fetchFn: () => Promise<T>,
  interval: number = 3000
): {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
}
```

**Behavior:**
- Initial fetch on mount
- Poll every 3 seconds
- Show subtle loading indicator (pulsing dot)
- Only update UI if data changed (deep equality check)
- Pause when tab not visible
- Resume when tab becomes visible

### Data Flow

```
User opens /sentinel page
    ↓
usePolling triggers fetchSentinelState()
    ↓
sentinelApi.ts returns mock state + actions (with traceIds)
    ↓
SentinelStatus renders StateMachineGraph + EnhancedActionTimeline
    ↓
User clicks "View trace in Weave" on action
    ↓
getWeaveTraceUrl(traceId) generates URL
    ↓
Browser opens new tab → https://weave.wandb.ai/traces/{traceId}
    ↓
Poll updates every 3s in original tab, new actions appear with smooth animation
```

## Existing Patterns to Reuse

From current codebase:

1. **Timeline styling** (`ActionTimeline.tsx`)
   - Keep color scheme (green/blue/amber/gray)
   - Maintain vertical connecting lines
   - Same timestamp formatting
   - Add link buttons following existing button patterns

2. **External links** (`Dashboard.tsx`, `SentinelStatus.tsx`)
   - Link component from react-router-dom for internal nav
   - Standard `<a>` tags for external URLs (Weave traces)
   - External link icon pattern (lucide-react `ExternalLink` icon)

3. **Status indicators** (throughout)
   - Pulse animations on active states
   - Status badges with color-coded backgrounds
   - Consistent spacing and typography

4. **Layout patterns** (`SentinelStatus.tsx`)
   - Grid-based responsive layout
   - Generous whitespace, soft borders
   - Sections with clear hierarchy

## Libraries to Add

**Required:**
- None! Can build with existing dependencies

**Optional (if custom SVG proves difficult):**
- `reactflow@11.11.4` - State machine graph (only if needed)
- All visualization can be done with Motion (already installed) + SVG

## Verification Plan

### Visual Testing
1. Open `/sentinel` page in browser
2. Verify state machine graph renders at top with current state highlighted
3. Click different state nodes → timeline filters to actions in that state
4. Verify timeline shows actions with "View trace in Weave →" link buttons
5. Click trace link → new tab opens with Weave URL (e.g., `https://weave.wandb.ai/traces/abc123`)
6. Verify external link icon appears next to button text
7. Check that disabled state works when traceId is missing

### Polling Behavior
1. Watch for updates every 3 seconds
2. Verify new actions appear with smooth animation (no flashing)
3. Check "Last updated" timestamp increments
4. Switch to different tab → verify polling pauses
5. Return to tab → verify polling resumes

### Link Generation Testing
1. Find action for "Memory leak detected"
2. Verify traceId is present and valid
3. Click "View trace in Weave" → URL format is correct
4. Check URL contains the action's traceId
5. Verify link opens in new tab (not same tab)
6. Confirm `rel="noopener noreferrer"` for security

### Mock Data Realism
1. Verify trace IDs are unique per action
2. Check span parent/child relationships form valid tree
3. Verify span timing is realistic (no negative durations, logical hierarchy)
4. Confirm attributes match what Sentinel would actually collect (`rss_mb`, `loop_lag_ms`, etc.)

### Design Consistency
1. Verify minimalist aesthetic maintained (off-white bg, soft borders)
2. Check typography hierarchy (same font weights as Dashboard)
3. Verify colors match existing palette (green/amber/red/blue for status)
4. Confirm generous whitespace between sections
5. Test responsive layout (desktop + mobile)

## Future Enhancement Path

**Phase 2 (Real Weave Integration):**
- Replace `sentinelApi.ts` mock with real HTTP calls
- Connect to W&B Weave API endpoints
- Handle authentication (API keys)
- Error states for failed trace fetches

**Phase 3 (Advanced Interactivity):**
- Metric overlay: show spans on memory/CPU charts
- Span filtering: hide non-critical spans
- Search/filter traces by attribute
- Export trace data (JSON download)

**Phase 4 (Real-time WebSocket):**
- Replace polling with WebSocket connection
- Stream actions as they happen (instant updates)
- Live state machine transitions

## Key Design Decisions

1. **Two-tier visualization** - State machine at top provides workflow context, timeline below shows detailed history
2. **External Weave links** - Opens trace in new tab using Weave's native UI, avoiding duplication of trace visualization
3. **Polling over WebSocket** - Simpler implementation, sufficient for 3-second updates
4. **Mock Weave URLs** - Future-proof URL generation that can swap for real Weave domain
5. **Custom SVG for state graph** - Maintains minimalist design, no heavy dependencies
6. **Link buttons on actions** - Simple, discoverable way to audit traces without cluttering UI
7. **Security best practices** - `rel="noopener noreferrer"` on external links

## Success Criteria

✅ Users can see Sentinel's current workflow state at a glance  
✅ Users can click any action to open Weave trace in new tab  
✅ Trace links generate correct Weave URLs with traceId  
✅ Page updates every 3 seconds with new actions  
✅ Design matches existing minimalist aesthetic  
✅ Mock data includes traceIds linking to realistic Weave URLs  
✅ Ready to swap mock URLs for real Weave domain  
