# Telegram Content Organizer — Project Plan

Status: Implementation in progress. The current guided topic publication and retrieval behavior is described in [README.md](README.md); older sections below preserve the broader roadmap and may describe later features.

## 1. Purpose and required sequence

Build a Python Telegram bot whose primary duty is to organize files and messages and publish them in the correct group topic. It then saves the organized content record in a database so approved users can retrieve it later.

The required sequence is:

1. An authorized user sends content to the bot privately.
2. The bot collects the project, destination topic, content category, title, and optional description through buttons and short prompts.
3. The user reviews the prepared post and confirms publication.
4. The bot assigns a permanent content ID and publishes the organized content to the selected topic.
5. After Telegram confirms publication, the bot saves the completed content record and its published message references in the database.
6. An authorized user searches by ID, name, description, or indexed content and receives the selected original content through the bot.

The group owner decides which numeric Telegram user IDs may use the bot. In the current version, an approved user may submit to registered topics and retrieve saved content; group membership alone does not grant bot access. Item restrictions remain available in the database for later use.

## 2. Storage and memory

| Store | Responsibility |
| --- | --- |
| Telegram group and topics | Published files, messages, and readable organizational posts |
| Database | Content IDs, metadata, original message text, attachment references, search index, permissions, and workflow state |

For text submissions, save the original text in the database. For attachments, save Telegram file references, original filenames, media types, and published message locations. Store extracted text separately for content search. Under the proposed first version, the original attachment bytes remain in Telegram.

The database record represents the organized content item and all its attachments. An independent copy of attachment bytes would be an additional storage/backup feature, to be decided before implementation.

The standard Bot API does not provide general historical group-message search. A hashtag supports human searching in Telegram, while the bot uses database mappings. Database backups are necessary; automatic reconstruction from the entire group history is not an assumed capability.

## 3. Owner authorization and access requests

### Owner identity

- Configure the owner's numeric Telegram user ID and managed group IDs during deployment.
- Verify that the configured owner is an administrator of the managed group during setup.
- Use numeric IDs for authorization. Usernames and display names are labels, since they can change.
- Never make the first person who starts the bot its owner automatically.
- Only the configured owner can approve users or delegate administrative authority. Other group admins do not automatically become bot administrators.

### Approval workflow

1. An unknown user starts the bot and sees an access-request screen.
2. The user requests access with an optional explanation.
3. The owner receives the numeric user ID, available profile labels, and explanation.
4. The owner selects Approve or Reject. Approval includes allowed projects and read/submit permissions.
5. The requester receives the decision.
6. The owner can change permissions or revoke access at any time.

Before approval, users cannot list projects, browse files, search, retrieve content, or start submissions. Rate-limit repeated access requests.

### Permissions

| Permission | Meaning |
| --- | --- |
| Bot access | Owner approval to use the bot |
| Read project | Search and retrieve eligible content in that project |
| Submit to project | Create submissions for that project |
| Item allowlist | Optional additional restriction on a specific content item |
| Owner | Manage users, permissions, configuration, and all content records |

Require approval plus the relevant project permission. If an item has an allowlist, require membership in that allowlist too. Missing permissions mean no access. The owner retains access to all managed records.

Check permissions for every search, preview, download, publication, edit, and button callback. Recheck immediately before delivery so old buttons cannot bypass revocation. Unauthorized records must not leak through titles, snippets, result counts, or exact-ID lookups.

Bot permissions govern delivery through the bot. People who can read the Telegram group may see its posts directly. Topics within one group must not be treated as separate access boundaries. Content requiring separation between clients should be published to separate chats with appropriate membership. Revocation cannot retract copies already received.

## 4. Guided submission workflow

1. **Receive:** Accept supported text, documents, photos, video, audio, or a confirmed collection of attachments. Create a draft associated with the sender.
2. **Project:** Show only projects where the sender can submit.
3. **Topic:** Show destinations registered for that project; suggest its default destination where configured.
4. **Category:** Ask what the material represents: drawing, invoice, contract, meeting notes, deliverable, or another configured category.
5. **Title:** Ask for a readable name; suggest the original filename when available.
6. **Description:** Collect optional explanation and search tags.
7. **Review:** Show the destination, details, and content with Publish, Edit, Back, and Cancel controls.
8. **Publish:** Assign the permanent ID, format the post, and send it to the chosen topic.
9. **Register:** Save the successful content record with Telegram's returned message identifiers.
10. **Confirm:** Return the ID and an Open in group button.

Detect the technical media type automatically. Ask the user for the business category: a PDF might be an invoice, drawing, or contract.

Projects, categories, and topic mappings are owner-managed database configuration, not hardcoded names. Register existing topics by sending their direct links to the bot in the owner's private chat; do not assume automatic enumeration of all historical topics.

Preserve original filenames and original user text. Use a separate display title for organization. An album or explicitly confirmed batch may become one item with multiple attachments; consecutive uploads are not automatically one batch.

## 5. Published post format

Example:

> **Ground Floor — Electrical Layout**  
> Project: Riverside Villa  
> Category: Drawing  
> Description: Updated socket positions following the site meeting.  
> Submitted by: Ali  
> Recorded: 10 October 2026  
> Reference: #CNT_7K9M2Q8R

Use the file caption where supported and within its length limit. Otherwise, publish a summary message and send the content as replies in the same topic. Save all message references, including every attachment.

Clearly show the destination in the preview. Define supported input types explicitly; non-copyable or unsupported Telegram messages must produce an explanation instead of a false success.

## 6. Unique content identity

Every item receives an application-owned primary key such as `CNT_7K9M2Q8R`. Enforce uniqueness in the database and regenerate on collision. Include it as a searchable hashtag in the published post.

The ID remains unchanged when metadata is edited. A newly submitted revision receives its own ID and links to the previous version. One record can include several attachments and published messages.

| Identifier | Purpose |
| --- | --- |
| Content ID | Permanent primary key for the organized item |
| Project ID | Project identity independent of its name or topic |
| Chat ID + message ID | Location of a Telegram message |
| Topic ID | Destination thread within a chat |
| File ID | Telegram reference used to resend an attachment |
| File unique ID | Supporting duplicate-detection signal; cannot be used to resend a file |

Filenames and Telegram file IDs do not replace the content primary key. The same attachment may legitimately belong to separate records or projects.

## 7. Search and original-content retrieval

Search inputs:

- Exact content ID.
- Title or original filename.
- Project, category, description, or tags.
- Original message text.
- Extracted attachment text for supported formats.

Retrieval sequence:

1. Verify that the requester is approved.
2. Search only records the requester may read.
3. Rank exact ID and title matches above broader text matches.
4. Show paginated choices when multiple items match, including title, project, category, date, and ID.
5. Recheck access when a result is selected.
6. Send the original selected content into the private bot conversation, preserving the supported media type and returning all attachments.
7. Include its organized summary and, where appropriate, a group-message link.

A group link alone does not satisfy retrieval. The bot must deliver the selected file/message when Telegram permits and the content remains available.

If a published message is unavailable, attempt delivery through its stored reusable file reference where permitted. If delivery fails, report the availability problem and notify the owner. Do not promise that deleted material is always recoverable.

### Meaning of searching by content

A file can be organized and returned even if its internal contents are not searchable. For the first release, search metadata, original text messages, and safely extracted text from an agreed set of document formats.

Track extraction as pending, complete, unsupported, or failed. Extraction failures must not block metadata search or ordinary retrieval.

OCR for images/scans, audio transcription, and semantic search are later increments unless selected for the initial release. Do not promise arbitrary understanding of every file type. Search results must resolve to real stored records and source content.

## 8. Proposed database records

| Record | Main data |
| --- | --- |
| User | Telegram ID, profile labels, approval state, approving owner, decision dates |
| Access request | Requester, explanation, decision, decision history |
| Project | Stable ID, name, description, active/archive state |
| Project permission | User ID, project ID, read and submit permissions |
| Destination | Group ID, topic ID, name, active state |
| Project destination | Project ID, destination ID, default flag |
| Category | Stable ID, name, active state |
| Submission draft | Sender, source references, collected details, current step |
| Content item | Content ID, project, category, title, description, tags, original text, submitter, dates, previous-version ID |
| Attachment | Content ID, position, media type, filename, file ID, file unique ID |
| Published message | Content ID, chat ID, topic ID, message ID, summary/attachment role |
| Search document | Content ID, extracted text, extraction method and status |
| Item restriction | Content ID and allowed user IDs, when restricted |
| Publication job | Draft, reserved content ID, attempts, returned message IDs, recovery state |
| Audit event | Actor, action, target record, time, result |

Use stable IDs for relationships and permissions. Store timestamps consistently and display them in the configured timezone.

## 9. Python application structure

Start with one application and one persistent database, separating responsibilities into modules:

| Component | Responsibility |
| --- | --- |
| Telegram interface | Messages, commands, buttons, and delivery |
| Authorization | Owner identity, approvals, project access, item restrictions |
| Submission | Guided questions, drafts, validation, preview |
| Catalog | Projects, topics, categories, records, and versions |
| Publication | Post formatting, topic routing, delivery recovery |
| Search and retrieval | Permission-filtered search and original-content delivery |
| Extraction worker | Document indexing and later OCR/transcription |
| Persistence | Database operations, migrations, backups, workflow state |
| Audit | Approval, publication, permission-change, and retrieval events |

Select an asynchronous Telegram library and database during implementation based on deployment needs. Separate services are unnecessary for the initial design.

## 10. Publication order and reliability

The user-visible order is **organize → publish → save the completed catalog record**.

Persist a minimal draft and publication job before sending to support crash recovery. This bookkeeping is not a successfully published search result. Reserve the content ID before publication so it can appear in the post.

Suggested states: draft, ready, publishing, published, indexed, failed, and needs review. A published item may be searchable by metadata while document extraction is still pending.

Telegram delivery and database persistence cannot be committed atomically. Save returned message IDs promptly and retry database finalization without resending messages already recorded as successful. If a timeout or crash leaves delivery uncertain, preserve the same content ID and flag the job for owner reconciliation rather than blindly resending it.

Required operational behavior:

- Persist drafts and isolate simultaneous user conversations.
- Deduplicate incoming updates and repeated Publish clicks.
- Handle temporary errors and Telegram rate limits with bounded retries.
- Track partially published multi-message records for recovery.
- Revalidate user permissions and destination availability before publishing.
- Keep secrets outside source control and back up the database and permissions.
- Apply size/time limits to document extraction; never execute uploaded content.
- Route metadata edits through the bot, updating the database and visible post with failures recorded for recovery.

## 11. Delivery phases

### Phase 1 — Organization and authorized retrieval

- Owner setup, access requests, approval/rejection, revocation, and project permissions.
- Configurable projects, registered topics, and categories.
- Guided submissions with preview and cancellation.
- Structured topic publication with immutable IDs.
- Durable catalog, attachment references, and recovery state.
- Search by ID, title, filename, metadata, and text messages.
- Original-content delivery for supported files/messages and collections.
- Document-text extraction for agreed initial formats.
- Database backups and audit records.

### Phase 2 — Richer search and file management

- OCR, transcription, and optional semantic search.
- Related versions, current-version selection, duplicate suggestions.
- Owner-assisted import of older content through a defined migration process.
- Optional independent attachment backups and expanded format support.

### Phase 3 — Project progress and client updates

- Tasks, milestones, owners, due dates, approvals, and status events.
- Content IDs linked to tasks and milestones as evidence.
- Client-specific permissions and delivery destinations.
- Owner-configured summaries, reminders, and notification rules.

An upload alone does not mean a milestone is complete or a client should be notified. Those actions require explicit workflow rules or authorized confirmation.

## 12. Acceptance criteria

1. Unapproved users cannot submit, search, enumerate, or retrieve managed content.
2. Approval grants only selected permissions; revocation blocks subsequent actions, including old buttons.
3. A supported submission creates an organized post in the selected topic with correct details and a unique ID.
4. Successful publication saves all message and attachment references.
5. ID, name, and indexed-content searches return only authorized matches.
6. Selecting a result returns its original content and attachments or a specific delivery failure.
7. Identically named items remain distinguishable by ID, project, date, and version relationship.
8. Restarts preserve approvals, catalog records, and unfinished drafts.
9. Repeated updates/clicks do not create duplicate jobs; uncertain delivery is exposed for recovery.
10. Unsupported inputs and extraction failures receive clear explanations without false success claims.

## 13. Details to settle before implementation

- Owner Telegram user ID and managed group IDs.
- Shared group versus separate groups per project/client, reflecting visibility requirements.
- Initial projects, topics, categories, and default destinations.
- Read/submit grants and whether item-specific restrictions are needed immediately.
- Initial document formats and languages for content extraction.
- Typical attachment sizes, daily volume, hosting environment, and backup destination.
- Whether original attachment bytes also require independent storage outside Telegram.

These are configuration and scope decisions. This document authorizes no deployment or implementation by itself.

## 14. Telegram reference documentation

- [Receiving updates and retention](https://core.telegram.org/bots/api#getting-updates)
- [Copying messages and topic routing](https://core.telegram.org/bots/api#copymessage)
- [File identifiers](https://core.telegram.org/bots/api#document)
- [Bot interaction features](https://core.telegram.org/bots/features)

Verify current API constraints and supported media behavior during implementation.
