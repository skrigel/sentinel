import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Dashboard } from './pages/Dashboard';
import { LandingPage } from './pages/LandingPage';
import { SentinelStatus } from './pages/SentinelStatus';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/sentinel" element={<SentinelStatus />} />
      </Routes>
    </BrowserRouter>
  );
}
