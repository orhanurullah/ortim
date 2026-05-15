# PRD: web-todo-proofpoint-v3

> **Status:** DRAFT
> **Author:** Analyst Agent
> **Project ID:** web-todo-proofpoint-v3

## 1. Problem
Individuals lack a simple, private, browser-based tool to track their personal tasks without relying on external servers or cloud accounts. Existing solutions require sign-up, expose data to third parties, or lack persistence across browser sessions.

## 2. Goals
- Enable users to create, view, complete, and delete personal tasks entirely within the browser
- Ensure all task data persists across browser sessions without requiring server infrastructure

## 3. Non-Goals
- Multi-user support or authentication system
- Task sharing, collaboration, or delegation between users
- Server-side data storage or synchronization across devices

## 4. Users
- **End User:** An individual who wants to manage their own personal tasks privately in a browser

## 5. User Stories
- As an end user, I want to create a new task with a title, so that I can record something I need to do.
- As an end user, I want to view all my tasks in a list, so that I can see what I need to accomplish.
- As an end user, I want to mark a task as completed, so that I can track my progress.
- As an end user, I want to delete a task, so that I can remove tasks I no longer need to track.
- As an end user, I want my tasks to persist after I close and reopen the browser, so that I don't lose my data.

## 6. Acceptance Criteria
- [ ] `npx vitest run` exits with code 0 (all tests pass)
- [ ] Application renders a text input and an "Add" button on initial load
- [ ] Typing text in the input and clicking "Add" creates a new task visible in the task list
- [ ] Each task in the list displays its title text and a completion checkbox
- [ ] Checking a task's checkbox visually marks it as completed (e.g., strikethrough text)
- [ ] Each task has a delete button that removes the task from the list when clicked
- [ ] After adding 3 tasks, closing the browser tab, reopening the app, all 3 tasks are still displayed
- [ ] After marking a task as completed, closing and reopening the browser, that task remains marked as completed
- [ ] After deleting a task, closing and reopening the browser, that task is absent from the list

## 7. Constraints
- **Compliance:** None (no PII collected, no server-side data)
- **Performance:** Application must load and become interactive within 3 seconds on a modern broadband connection
- **Budget:** None (open-source, no paid services required)
- **Timeline:** None specified
- **Other hard requirements:** All data must persist using localStorage (survives page refreshes and browser restarts). Single-user application with no authentication.

## 8. Open Questions
- **[NEEDS-INPUT]** What is the expected data model for a task? Does a task have only a title/description, or also a due date, priority, category, etc.?
- **[NEEDS-INPUT]** Should the UI be responsive/mobile-friendly, or desktop-only?
- **[NEEDS-INPUT]** Are there any accessibility requirements (WCAG level, keyboard navigation, screen reader support)?
- **[NEEDS-INPUT]** What is the target browser support (modern evergreen only, or legacy browsers like IE11)?
- **[NEEDS-INPUT]** Should the application support task editing (modifying an existing task's title/description) after creation?
- **[NEEDS-INPUT]** Is there a need for task ordering/sorting (by creation date, alphabetically, manual drag-and-drop)?
- **[NEEDS-INPUT]** Should completed tasks be hidden, shown with a strikethrough, or moved to a separate section?

## 9. Out of Scope (Now)
- Task categories, tags, or priority levels
- Due dates, reminders, or notifications
- Search or filter functionality
- Dark mode or theme customization
- Export/import of task data
- Undo functionality for delete operations

---

*PRD must contain zero technical implementation choices. Tech stack belongs in the RFC.*

## Extension 1 — Task Tagging

### Goal
Allow users to assign one or more tags to tasks and filter the task list by tag, enabling better organization and quick retrieval of related tasks.

### Affected User Stories
- **NEW** — As an end user, I want to assign tags to my tasks, so that I can categorize and organize them.
- **NEW** — As an end user, I want to filter my task list by a specific tag, so that I can see only tasks related to that category.
- **EXTENDED** — As an end user, I want to view all my tasks in a list, and now also see their assigned tags displayed alongside the task title (extends the existing "view all tasks" story).

### Affected Modules
- `src/` — extends; adds tag input UI on task creation, tag display on each task row, and a tag filter bar above the task list.
- *(No new modules; tag data is stored as a new field on the existing Task entity in localStorage.)*

### Acceptance Criteria
- [ ] `npx vitest run` exits with code 0 (all existing tests pass, new tests pass)
- [ ] On task creation, user can type one or more comma-separated tags in a dedicated input field (e.g., "work, urgent")
- [ ] Each task in the list displays its tags as small badges/chips below the task title
- [ ] A filter bar above the task list shows all unique tags that exist across all tasks
- [ ] Clicking a tag in the filter bar filters the task list to show only tasks that have that tag
- [ ] Clicking the same tag again removes the filter and shows all tasks
- [ ] Multiple tags can be selected in the filter (AND logic: task must have all selected tags)
- [ ] After adding tags to a task, closing and reopening the browser, those tags persist and are displayed
- [ ] After filtering by a tag, closing and reopening the browser, the filter is reset (no persistent filter state)
- [ ] Deleting a task also removes its tags from the tag filter bar if no other task uses that tag

### Non-Goals
- No tag management UI (create/edit/delete tags independently of tasks)
- No tag color customization or ordering
- No tag search or autocomplete
- No tag statistics or analytics

### Open Questions
- **[NEEDS-INPUT]** Should tags be free-form text, or should there be a predefined set of tags the user can choose from?
- **[NEEDS-INPUT]** Should the tag filter support OR logic (show tasks that have any of the selected tags) instead of AND logic?
- **[NEEDS-INPUT]** Should completed tasks be excluded from tag filter results, or should they still appear?
