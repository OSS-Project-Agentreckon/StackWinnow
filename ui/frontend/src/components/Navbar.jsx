import { NavLink } from 'react-router-dom'

const links = [
  { to: '/recommend', label: 'Discover tools' },
  { to: '/inspect', label: 'Inspect source' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/workflow', label: 'Workflow' },
]

export default function Navbar() {
  return (
    <nav className="bg-indigo-700 text-white shadow">
      <div className="max-w-6xl mx-auto px-4 flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <span className="font-bold text-lg tracking-tight">StackWinnow</span>
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `text-sm font-medium px-2 py-1 rounded transition-colors ${
                isActive ? 'bg-indigo-500' : 'hover:bg-indigo-600'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
