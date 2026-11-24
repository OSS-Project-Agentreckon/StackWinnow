import { useId } from 'react'

export default function DiscoveryRefinements({
  goals,
  goalInput,
  onGoalInputChange,
  onAddGoal,
  onRemoveGoal,
  hasOtherRefinement = false,
  description = 'Goals are not required. Add a priority to refine the suggestions from your code.',
  children,
}) {
  const goalId = useId()

  return (
    <details
      className="rounded-lg border border-gray-200 p-4"
      open={goals.length > 0 || hasOtherRefinement || undefined}
    >
      <summary className="cursor-pointer text-sm font-medium text-gray-700">
        Optional refinements
        {goals.length > 0 && (
          <span className="ml-2 text-xs text-indigo-600">
            {goals.length} goal{goals.length === 1 ? '' : 's'} active
          </span>
        )}
      </summary>
      <div className="mt-4 space-y-4">
        <p className="text-sm text-gray-500">{description}</p>
        <div>
          <label htmlFor={goalId} className="block text-sm font-medium text-gray-700 mb-1">
            Goals or priorities (optional)
          </label>
          <div className="flex flex-wrap gap-2 mb-2">
            {goals.map(goal => (
              <span key={goal} className="bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full flex items-center gap-1">
                {goal}
                <button
                  type="button"
                  aria-label={'Remove goal: ' + goal}
                  onClick={() => onRemoveGoal(goal)}
                  className="text-indigo-500 hover:text-indigo-700"
                >&times;</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              id={goalId}
              className="min-w-0 flex-1 border rounded px-3 py-1.5 text-sm"
              placeholder="e.g. reduce costs, evaluate answers"
              value={goalInput}
              onChange={event => onGoalInputChange(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  onAddGoal()
                }
              }}
            />
            <button
              type="button"
              onClick={() => onAddGoal()}
              className="px-3 py-1.5 bg-gray-100 rounded text-sm hover:bg-gray-200"
            >Add</button>
          </div>
        </div>
        {children}
      </div>
    </details>
  )
}
