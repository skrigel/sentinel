import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Dashboard } from './pages/Dashboard';
import { SentinelStatus } from './pages/SentinelStatus';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/sentinel" element={<SentinelStatus />} />
      </Routes>
    </BrowserRouter>
  );
}