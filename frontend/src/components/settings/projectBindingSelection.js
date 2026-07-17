export function chooseActiveProjectId(
  activeProjects,
  currentSelection,
  currentProject,
) {
  const projects = Array.isArray(activeProjects) ? activeProjects : []
  const activeIds = new Set(projects.map(project => project.id))
  if (activeIds.has(currentSelection)) return currentSelection
  if (activeIds.has(currentProject?.id)) return currentProject.id
  return projects[0]?.id || ''
}
