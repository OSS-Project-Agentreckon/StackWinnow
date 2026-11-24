import { Routes, Route, Navigate } from 'react-router-dom'
import Navbar from './components/Navbar'
import Catalog from './pages/Catalog'
import Inspect from './pages/Inspect'
import Recommend from './pages/Recommend'
import Workflow from './pages/Workflow'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/catalog" replace />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/inspect" element={<Inspect />} />
          <Route path="/recommend" element={<Recommend />} />
          <Route path="/workflow" element={<Workflow />} />
        </Routes>
      </main>
    </div>
  )
}
