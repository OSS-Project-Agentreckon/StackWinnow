import { Routes, Route, Navigate } from 'react-router-dom'
import { WorkbenchProvider } from './workbench/Context'
import Shell from './workbench/Shell'
import Discovery from './workbench/Discovery'
import Coverage from './workbench/Coverage'
import Catalog from './workbench/Catalog'
import Manage from './workbench/Manage'
import { Profiles, Reports, Environment } from './workbench/Utilities'

export default function App() {
  return <WorkbenchProvider><Shell><Routes>
    <Route path="/" element={<Navigate to="/recommend" replace/>}/>
    <Route path="/recommend" element={<Discovery/>}/>
    <Route path="/inspect" element={<Coverage/>}/>
    <Route path="/catalog" element={<Catalog/>}/>
    <Route path="/workflow" element={<Manage/>}/>
    <Route path="/profiles" element={<Profiles/>}/>
    <Route path="/reports" element={<Reports/>}/>
    <Route path="/environment" element={<Environment/>}/>
    <Route path="*" element={<Navigate to="/recommend" replace/>}/>
  </Routes></Shell></WorkbenchProvider>
}
