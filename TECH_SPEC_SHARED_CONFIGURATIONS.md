# Shared Configurations for GeM Tender Scraping
## Technical Design Document
### Version 0.1

---

## Revision History

| Version | Date of Change | Author / Email | Reviewed / Approved By / Email | Change Description |
|---------|-----------------|-----------------|-------------------------------|-------------------|
| Draft | 01-03-2026 | TenderGyan Team | | Initial draft |
| Version 0.1 | 01-03-2026 | TenderGyan Team | | |
| Version 1.0 | dd-mon-yyyy | <Full Name> | <Full Name> | |

---

## DISCLAIMER

This document is strictly confidential and proprietary to TenderGyan. It is intended solely for internal design, review, and implementation purposes. Distribution outside authorized recipients is prohibited.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Scope of Work](#2-scope-of-work)
3. [Assumptions](#3-assumptions)
4. [Dependencies/Constraints/Risk/Gaps](#4-dependenciesconstraintsriskgaps)
5. [Technology Stack](#5-technology-stack)
6. [Definitions](#6-definitions)
7. [Architecture Overview](#7-architecture-overview)
8. [Application and Process Flow](#8-application-and-process-flow)
9. [Data Model](#9-data-model)
10. [UI Solution](#10-ui-solution)
11. [Non-Functional Requirements](#11-non-functional-requirements)
12. [System Integration and Monitoring](#12-system-integration-and-monitoring)
13. [Error Management](#13-error-management)
14. [Security & Governance](#14-security--governance)
15. [Version Control and Coding Standards](#15-version-control-and-coding-standards)
16. [System Policies](#16-system-policies)
17. [References](#17-references)
18. [Appendix](#18-appendix)

---

## 1. Introduction

### 1.1. Background / Business Problem / Business Overview

Currently in TenderGyan, when multiple organizations want to monitor the same type of tenders (for example, "valve" tenders), each organization has its own separate search configuration. This results in:

- **Redundant Scraping**: The system scrapes the same GeM website multiple times for identical search keywords
- **Configuration Management Overhead**: Admins must update search configurations for each organization separately
- **Resource Inefficiency**: Network bandwidth and processing power wasted on duplicate downloads
- **Maintenance Complexity**: Keyword updates require changes across multiple configurations
- **Email Scheduling Issues**: Each organization maintains independent email schedules, complicating coordination

**Business Problem**: Organizations in similar business domains (valve manufacturers, conveyor manufacturers, etc.) want to monitor the same tender categories but may have different matching keywords and notification recipients. Currently, this requires duplicating the entire search and analysis pipeline per organization, which is inefficient.

### 1.2. Purpose

This document describes a three-phase architecture to support shared search configurations, where:
1. **Phase 1** (Download): Tenders are scraped once per configuration and stored centrally
2. **Phase 2** (Analysis): Tenders are analyzed once per configuration with status tracking
3. **Phase 3** (Email): Results are distributed to organizations per their matching keywords and scheduled email times

This eliminates redundant scraping while maintaining organization-specific customization.

### 1.3. Intended Audience
- Backend engineers
- Frontend engineers
- QA and testing teams
- DevOps and deployment teams
- Product and business stakeholders

### 1.4. Related Documents

| Sr.No. | Document Name | Location / Link |
|--------|---------------|-----------------|
| 1 | Current System Architecture | Internal wiki |
| 2 | GeM API Documentation | External |
| 3 | Database Schema Documentation | Internal repo |

---

## 2. Scope of Work

### Backend Processing
- Modify `gem_search_configurations` table to act as master configuration (store search terms like 'valve', 'conveyor')
- Create new table `gem_org_search_capabilities` for organization-specific matching keywords
- Create new table `gem_search_task_execution` to track download and analysis execution status
- Create new table `gem_org_email_mappings` to store org-config-email relationships
- Update `gem_scheduler.py` to:
  - Execute Phase 1 jobs based on master configurations only (no org iteration)
  - Execute Phase 2 jobs based on organization capabilities with dependency checks
  - Execute Phase 3 email jobs based on email mappings and schedules
- Modify `gem_nlp_api.py` to:
  - Accept configuration ID instead of org-specific parameters
  - Process one search for all associated organizations
  - Mark analysis completion in `gem_search_task_execution`
- Update `gem_email_notifier.py` to:
  - Query email mappings per organization
  - Send emails based on organization-specific schedule
  - Track email delivery status

### Database Changes
- Create `gem_org_search_capabilities` table
- Create `gem_search_task_execution` table with status tracking
- Create `gem_org_email_mappings` table
- Add foreign key relationships
- Add execution time and status columns to support scheduling

### Phase 1: Download Service
- Download tenders based on master search configurations
- Store tenders in central repository (database/file system)
- Update execution status to 'Completed' or 'Failed'
- Retry mechanism with exponential backoff on failure

### Phase 2: Analysis Service
- Poll `gem_search_task_execution` to check if Phase 1 completed
- Retry every 5 minutes if Phase 1 still running or pending
- Once Phase 1 completes, run NLP analysis
- Map results to all organizations with this configuration
- Mark analysis complete in `gem_search_task_execution`

### Phase 3: Email Service
- Query email mappings for completed analyses
- Send emails to organization recipients
- Track email delivery status and timestamps

### 2.1. Out of Scope

- Changes to GeM API integration (external API remains unchanged)
- Frontend portal changes for end-users
- Real-time notifications or webhooks in v1
- Multi-language tender support beyond existing system
- Bulk import of search configurations from external sources
- API authentication changes

---

## 3. Assumptions

- Organizations are separate but share infrastructure and database
- Search configurations are created by superadmin on superadmin dashboard
- Matching keywords are comma-separated strings (v1 limitation; regex patterns in future)
- Each organization belongs to a single superadmin (no cross-org configuration visibility)
- Execution times are in UTC and stored in 24-hour format (HH:MM)
- Database supports transactions (for status atomicity)
- Network connectivity to GeM portal is available during Phase 1 execution
- Email delivery infrastructure is operational during Phase 3 execution
- Analysis (NLP) takes less than 5 minutes between retry checks in Phase 2
- One search configuration can be assigned to multiple organizations
- Organizations may have overlapping but not identical matching keywords for the same configuration

---

## 4. Dependencies/Constraints/Risk/Gaps

| Type | Description | Severity | Mitigation |
|------|-------------|----------|-----------|
| Dependency | GeM website availability and API stability | High | Implement retry logic with exponential backoff; log failures |
| Dependency | NLP/LLM service availability for analysis | High | Fallback to simpler keyword matching; queue analysis jobs |
| Constraint | Execution time scheduling limited to 24-hour UTC format | Medium | Document timezone requirements; provide admin UI to display org timezone |
| Risk | Phase 1 failures prevent Phase 2 from executing | High | Implement robust error logging and admin alerts; manual retry capability |
| Risk | Email delivery failures go unnoticed | Medium | Log all email attempts; implement delivery confirmation tracking |
| Risk | Database lock contention during concurrent Phase 1 jobs | Medium | Implement job locking mechanism; stagger execution times |
| Risk | Stale tender data if Phase 1 fails silently | High | Implement health checks and monitoring; alert on missed executions |
| Gap | No user-facing UI for searching shared configurations | Medium | Phase 2 implementation; frontend team to design UI |
| Gap | No audit trail for configuration changes | Medium | Add change log tracking in future version |

---

## 5. Technology Stack

| Component | Technology | Version | Comments |
|-----------|-----------|---------|----------|
| Web Framework | Flask | 2.x | Existing |
| Database | SQLite / PostgreSQL | Latest | Existing; supports transactions required for Phase 2 |
| Scheduler | APScheduler | 3.x | Existing; extended for Phase 1/2/3 separation |
| NLP/LLM | Google Gemini / Custom LLM | Latest | Existing; used in Phase 2 |
| Email Service | SMTP (Gmail/SendGrid) | Native | Existing; extended for org-specific scheduling |
| Logging | Python logging | Native | Existing; enhanced with execution status logging |
| ORM | SQLAlchemy / Direct SQL | 2.x | Existing |
| Vector Store | FAISS / pgvector | Latest | Existing; used in Phase 2 analysis |
| Testing | pytest | Latest | Existing |
| Version Control | Git | Latest | Existing |

---

## 6. Definitions

| Term / Abbreviation | Description |
|-------------------|-------------|
| Master Configuration | Search configuration (e.g., 'valve', 'conveyor') created by superadmin in `gem_search_configurations` |
| Organization Capability | Organization-specific matching keywords and email settings in `gem_org_search_capabilities` |
| Phase 1 | Download phase: scrape GeM for tenders matching master configuration |
| Phase 2 | Analysis phase: run NLP on downloaded tenders and match against org keywords |
| Phase 3 | Email phase: send matched results to organization email recipients |
| Execution Status | State of Phase 1/2 jobs: 'Not Started Yet', 'Running', 'Completed', 'Failed' |
| Task Execution | Record in `gem_search_task_execution` tracking Phase 1 and Phase 2 progress |
| Email Mapping | Link between organization, configuration, and email recipient in `gem_org_email_mappings` |
| Retry Interval | 5-minute interval for Phase 2 to check Phase 1 completion status |
| Deduplication | Reusing Phase 1 and Phase 2 results across multiple organizations with same configuration |

---

## 7. Architecture Overview

### 7.1. Understanding of Current System Architecture

**Current Flow** (Per Organization):
```
gem_scheduler (APScheduler)
    ↓
gem_search_configurations (per org)
    ↓
Define search keyword (e.g., "valve")
    ↓
Execute scrape from GeM
    ↓
Store tenders in database
    ↓
gem_nlp_api.py (per tender per org)
    ↓
Match against org's keywords
    ↓
Generate analysis report
    ↓
gem_email_notifier.py
    ↓
Send email to org recipients
```

**Issue**: If 5 organizations search for "valve", the GeM website is scrapped 5 times and NLP analysis runs 5 times.

### 7.2. Proposed Architecture

**New Flow** (Master + Organization):
```
geo_scheduler (APScheduler) - ENHANCED
    │
    ├─── PHASE 1: Download (Master Configuration)
    │    gem_search_configurations (shared)
    │    ↓
    │    Download "valve" tenders ONCE for all organizations
    │    ↓
    │    gem_search_task_execution (status = 'Completed')
    │
    ├─── PHASE 2: Analysis (Per Organization Capability)
    │    gem_org_search_capabilities (per org per config)
    │    ↓
    │    Check if Phase 1 completed (dependency)
    │    ↓
    │    Run NLP analysis ONCE on downloaded tenders
    │    ↓
    │    Match results against org's keywords
    │    ↓
    │    gem_search_task_execution (status = 'Completed')
    │
    └─── PHASE 3: Email (Per Organization)
         gem_org_email_mappings (org-config-email)
         ↓
         Check if Phase 2 completed
         ↓
         Send email to org recipients at scheduled time
         ↓
         Track delivery in database
```

**Key Difference**: Phase 1 and Phase 2 run once per configuration, not per organization. Phase 3 runs per organization.

#### 7.2.1. System Characteristics

- **Execution Model**: Asynchronous (APScheduler-based job queuing). Each phase is independent with status tracking.
- **Expected Concurrency**: Multiple Phase 1 jobs may run concurrently (different configurations). Phase 2 jobs dependent on Phase 1 completion may queue or retry. Phase 3 jobs run serially per organization.
- **Scalability Considerations**:
  - Master configurations scale horizontally (new search terms)
  - Organization capabilities scale with number of organizations per configuration
  - Database query performance critical for status polling in Phase 2
  - Email delivery may need batching for large recipient lists
- **Security Posture**:
  - Superadmin only creates/edits master configurations
  - Organization admins manage their own keywords and email recipients
  - Email addresses never stored in plain text (encrypt in database)
  - Audit logging for configuration changes
- **Fault Tolerance**:
  - Phase 1 failures prevent Phase 2 from running (by design)
  - Phase 2 retries every 5 minutes for up to N attempts
  - Phase 3 failures logged and alerted; email retry on next scheduled time
  - All status transitions logged for debugging

---

## 8. Application and Process Flow

### 8.1. High-Level Process Flow

```
┌─────────────────────────────────────────────────────────────┐
│ ADMIN SETUP (One-time)                                      │
│                                                             │
│ 1. Superadmin creates "Valve" configuration                │
│ 2. Org A, Org B, Org C link to "Valve" config             │
│ 3. Each org defines their matching keywords                │
│ 4. Each org sets email recipients and schedule times       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ AUTOMATED RECURRING EXECUTION (Scheduled)                  │
│                                                             │
│ ┌───── PHASE 1: Download (2:00 PM) ─────┐                 │
│ │ Download "Valve" tenders ONCE          │                 │
│ │ Status → 'Completed' / 'Failed'        │                 │
│ └────────────────────────────────────────┘                 │
│                     ↓                                        │
│ ┌───── PHASE 2: Analyze (3:00 PM) ──────┐                 │
│ │ Poll: Is Phase 1 'Completed'?         │                 │
│ │ No  → Sleep 5 mins, retry             │                 │
│ │ Yes → Run NLP analysis ONCE           │                 │
│ │       Map results to all orgs          │                 │
│ │       Status → 'Completed' / 'Failed' │                 │
│ └────────────────────────────────────────┘                 │
│                     ↓                                        │
│ ┌───── PHASE 3: Email (Per Org) ────────┐                 │
│ │ Org A: Send at 4:00 PM                │                 │
│ │ Org B: Send at 5:00 PM                │                 │
│ │ Org C: Send at 6:00 PM                │                 │
│ └────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

### 8.2. Detailed Application Flow

#### **PHASE 1: Download Tenders**

**Trigger**: APScheduler fires job at scheduled time from `gem_search_configurations.phase_1_execution_time` (e.g., 2:00 AM UTC)

**Detailed Execution Flow**:

1. **Scheduler checks what to run**:
   - Query: `SELECT * FROM gem_search_configurations WHERE is_active=TRUE AND execution_time = '02:00'`
   - Example: Finds "Valve" config with search_keyword = "valve"

2. **For each configuration found**:

   **Step A: Check if already running**
   - Query: `SELECT status FROM gem_search_task_execution WHERE config_id=? AND phase='DOWNLOAD' AND DATE(started_at)=TODAY ORDER BY started_at DESC LIMIT 1`
   - If status = 'Running': Skip (another instance already running, prevent parallel execution)
   - If status = 'Failed': Mark as 'Not Started Yet' to retry

   **Step B: Mark job as Running**
   - Insert/Update in `gem_search_task_execution`:
     ```
     {
       execution_id: NEW_UUID,
       config_id: "valve-config-id",
       org_id: NULL (Phase 1 is config-level, not org-level),
       phase: 'DOWNLOAD',
       status: 'Running',
       started_at: 2024-03-01 02:00:00,
       completed_at: NULL,
       error_message: NULL,
       retry_count: 0
     }
     ```

   **Step C: Download tenders from GeM**
   - Call GeM scraper with search_keyword = "valve"
   - Scraper goes to GeM website/API and searches for "valve" tenders
   - Returns: List of tender objects (ID, title, description, value, deadline, etc.)
   - Example result: Found 245 new valve tenders

   **Step D: Store tenders in database**
   - Insert all 245 tenders into `tenders` table:
     ```
     {
       tender_id: "GEM-12345",
       config_id: "valve-config-id",
       title: "Valve procurement for BHEL",
       description: "High pressure ball valves...",
       source_url: "https://gem.gov.in/...",
       created_at: 2024-03-01,
       ...other fields
     }
     ```

   **Step E (SUCCESS): Mark job as Completed**
   - Update `gem_search_task_execution`:
     ```
     {
       status: 'Completed',
       completed_at: 2024-03-01 02:15:00,
       tenders_processed: 245,
       error_message: NULL
     }
     ```
   - Log: "Phase 1 completed for config 'Valve': 245 tenders downloaded"

   **Step E (FAILURE): Mark job as Failed and retry**
   - If GeM API times out or connection fails:
     - Update `gem_search_task_execution`:
       ```
       {
         status: 'Failed',
         completed_at: NULL,
         error_message: "Connection timeout after 5 retries",
         retry_count: 1
       }
       ```
     - Log error with stack trace
     - Check retry_count < 5:
       - YES: Queue Phase 1 job to run again in 5 minutes
       - NO: Alert admin: "Phase 1 failed for 'Valve' config after 5 retries. Manual intervention needed."

**Example Scenario**:
```
2:00 AM: Scheduler runs Phase 1 for "Valve" config
        ↓
2:00 - 2:15 AM: Downloading 245 tenders from GeM
        ↓
2:15 AM: Job succeeds. Status = 'Completed'
        ↓
Now Phase 2 can wait for this to complete and start at 3:00 AM
```

**Database State After Phase 1**:
```
gem_search_task_execution:
├─ execution_id: "exec-xxx"
├─ config_id: "valve-config"
├─ org_id: NULL
├─ phase: 'DOWNLOAD'
├─ status: 'Completed'
├─ started_at: 2024-03-01 02:00:00
├─ completed_at: 2024-03-01 02:15:00
├─ tenders_processed: 245
└─ error_message: NULL

tenders table:
├─ 245 new rows added with config_id = "valve-config"
```

---

#### **PHASE 2: Analyze Tenders per Organization**

**Trigger**: APScheduler fires job at scheduled time from `gem_org_search_capabilities.phase_2_execution_time` (e.g., 3:00 AM UTC)

**Detailed Execution Flow**:

1. **Scheduler checks what to run**:
   - Query: `SELECT * FROM gem_org_search_capabilities WHERE is_active=TRUE AND phase_2_execution_time = '03:00'`
   - Example: Finds:
     - Org A linked to "Valve" config (matching_keywords: "ball_valve,gate_valve")
     - Org B linked to "Valve" config (matching_keywords: "check_valve,butterfly_valve")

2. **For each capability (org + config pair)**:

   **SCENARIO 1: Phase 1 NOT Completed Yet**
   - At 3:00 AM, check Phase 1 status:
     ```
     Query: SELECT status FROM gem_search_task_execution
            WHERE config_id='valve-config' AND phase='DOWNLOAD'
            ORDER BY started_at DESC LIMIT 1
     Result: status = 'Running' (Phase 1 still downloading at 2:55 AM)
     ```
   - Action:
     - Log: "Waiting for Phase 1 'Valve' to complete (config_id='valve-config')"
     - Increment retry counter for this Phase 2 job
     - Query execution history to check retry_count for this Phase 2 job
     - If retry_count < 12:
       - Queue Phase 2 to run again in 5 minutes (3:05 AM)
       - Job exits gracefully
     - If retry_count >= 12:
       - Mark Phase 2 as 'Failed' in `gem_search_task_execution`
       - Alert admin: "Phase 2 for Org A 'Valve' timed out waiting for Phase 1 after 1 hour"
       - Skip processing for this org-config pair

   **Timeline of Retry Loop (Phase 1 not yet done)**:
   ```
   3:00 AM: Phase 2 starts for Org A
            Check Phase 1 status: 'Running'
            Queue retry in 5 mins (retry_count=1)
            ↓
   3:05 AM: Phase 2 starts for Org A
            Check Phase 1 status: 'Running' (2:15 mins remaining)
            Queue retry in 5 mins (retry_count=2)
            ↓
   3:10 AM: Phase 2 starts for Org A
            Check Phase 1 status: 'Completed' ✓
            Continue to Step B
   ```

   **SCENARIO 2: Phase 1 Completed Successfully**
   - At 3:10 AM (after retries), check Phase 1 status:
     ```
     Query: SELECT status FROM gem_search_task_execution
            WHERE config_id='valve-config' AND phase='DOWNLOAD'
            ORDER BY started_at DESC LIMIT 1
     Result: status = 'Completed'
     ```
   - Action: Proceed with analysis

   **Step A: Fetch downloaded tenders from Phase 1**
   - Query: `SELECT * FROM tenders WHERE config_id='valve-config' AND created_at >= TODAY ORDER BY created_at DESC`
   - Result: Gets all 245 tenders downloaded in Phase 1

   **Step B: Mark analysis as Running**
   - Insert in `gem_search_task_execution`:
     ```
     {
       execution_id: NEW_UUID,
       config_id: "valve-config-id",
       org_id: "org-a-id",
       phase: 'ANALYSIS',
       status: 'Running',
       started_at: 2024-03-01 03:10:00,
       completed_at: NULL,
       error_message: NULL,
       retry_count: 0
     }
     ```

   **Step C: Run NLP analysis for Org A**
   - For Org A with matching_keywords: "ball_valve,gate_valve"
   - Process each tender from Phase 1:
     ```
     For tender in 245_tenders:
       1. Extract main text from tender (title + description)
       2. Call NLP/LLM service:
          input: tender_title, tender_description, keywords=["ball_valve","gate_valve"]
          output: {matched: true/false, confidence_score: 0.85, matched_keywords: ["ball_valve"]}
       3. If matched == true:
          Store in database (Step D)
     ```
   - Example: Out of 245 tenders, 32 match "ball_valve" or "gate_valve"

   **Step D: Store matches in `matched_tenders` table for Org A**
   - Insert 32 records:
     ```
     {
       match_id: NEW_UUID,
       tender_id: "GEM-12345",
       config_id: "valve-config-id",
       org_id: "org-a-id",
       matched_keywords: "ball_valve",
       confidence_score: 0.92,
       email_sent: FALSE,
       created_at: 2024-03-01 03:15:00
     }
     ```

   **Step E: Repeat for Org B**
   - Same process but with Org B's matching_keywords: "check_valve,butterfly_valve"
   - Result: 28 matched tenders inserted for Org B
   - Both Org A and Org B get results from the SAME 245 Phase 1 tenders
   - **This is the deduplication benefit**: Phase 1 downloaded only once, Phase 2 ran once per org

   **Step F (SUCCESS): Mark analysis as Completed**
   - Update `gem_search_task_execution` for Org A:
     ```
     {
       status: 'Completed',
       completed_at: 2024-03-01 03:20:00,
       tenders_matched: 32,
       error_message: NULL
     }
     ```
   - Update for Org B:
     ```
     {
       status: 'Completed',
       completed_at: 2024-03-01 03:25:00,
       tenders_matched: 28,
       error_message: NULL
     }
     ```

**Example Full Scenario**:
```
2:00 AM: Phase 1 starts for "Valve" config
        Download 245 tenders
        ↓
2:15 AM: Phase 1 completes
        Status = 'Completed'
        ↓
3:00 AM: Phase 2 starts for Org A
        Check Phase 1: 'Completed' ✓
        Run NLP for Org A's keywords
        Store 32 matches for Org A
        ↓
3:20 AM: Phase 2 completes for Org A
        ↓
3:00 AM: Phase 2 starts for Org B (same time, different process)
        Check Phase 1: 'Completed' ✓
        Run NLP for Org B's keywords
        Store 28 matches for Org B
        ↓
3:25 AM: Phase 2 completes for Org B
        ↓
Now Phase 3 can send emails when scheduled
```

**Database State After Phase 2**:
```
gem_search_task_execution (2 new rows):
├─ (For Org A)
│  ├─ config_id: "valve-config"
│  ├─ org_id: "org-a-id"
│  ├─ phase: 'ANALYSIS'
│  ├─ status: 'Completed'
│  ├─ started_at: 2024-03-01 03:10:00
│  ├─ completed_at: 2024-03-01 03:20:00
│  └─ tenders_matched: 32
│
└─ (For Org B)
   ├─ config_id: "valve-config"
   ├─ org_id: "org-b-id"
   ├─ phase: 'ANALYSIS'
   ├─ status: 'Completed'
   ├─ started_at: 2024-03-01 03:00:00
   ├─ completed_at: 2024-03-01 03:25:00
   └─ tenders_matched: 28

matched_tenders table:
├─ 32 rows for Org A (tender_id, matched_keywords="ball_valve", email_sent=FALSE)
└─ 28 rows for Org B (tender_id, matched_keywords="check_valve", email_sent=FALSE)
```

---

#### **PHASE 3: Send Emails to Organization Recipients**

**Trigger**: APScheduler fires job at scheduled time from `gem_org_email_mappings.email_send_time` (e.g., 4:00 AM UTC for Org A, 5:00 AM UTC for Org B)

**Detailed Execution Flow**:

1. **Scheduler checks what to run**:
   - Query: `SELECT * FROM gem_org_email_mappings WHERE is_active=TRUE AND email_send_time = '04:00'`
   - Example at 4:00 AM: Finds:
     - Org A, Valve config, recipient: procurement@org-a.com

2. **For each email mapping**:

   **Step A: Check if Phase 2 analysis is completed**
   - Query:
     ```
     SELECT status FROM gem_search_task_execution
     WHERE config_id='valve-config'
     AND org_id='org-a-id'
     AND phase='ANALYSIS'
     ORDER BY started_at DESC LIMIT 1
     ```
   - Result check:
     - If status = 'Running': Phase 2 still analyzing
     - If status = 'Not Started Yet': Phase 2 hasn't started
     - If status = 'Failed': Phase 2 analysis failed
     - If status = 'Completed': Proceed to Step B

   **SCENARIO 1: Phase 2 NOT Completed**
   - If Phase 2 status ≠ 'Completed':
     - Log: "Phase 2 analysis not complete for Org A 'Valve'. Skipping email."
     - Skip email sending
     - Email will be sent on next scheduled time (tomorrow at 4:00 AM) if Phase 2 is done by then
     - Job exits gracefully (no alert, expected behavior)

   **SCENARIO 2: Phase 2 Completed Successfully**
   - If Phase 2 status = 'Completed':
     - Log: "Phase 2 complete for Org A. Sending email."

   **Step B: Fetch matched tenders**
   - Query:
     ```
     SELECT * FROM matched_tenders
     WHERE config_id='valve-config'
     AND org_id='org-a-id'
     AND email_sent=FALSE
     ORDER BY created_at DESC
     ```
   - Result: 32 matched tenders (from Phase 2)

   **Step C: Check if any tenders to send**
   - If no matched tenders found:
     - Log: "No new tenders to send for Org A. Skipping email."
     - Skip to next mapping
   - If matched tenders found:
     - Proceed to Step D

   **Step D: Prepare email content**
   - Build email subject:
     ```
     Subject: "32 New Valve Tenders Matched - Action Required"
     ```
   - Build email body with HTML template:
     ```
     Dear Procurement Team at Org A,

     We found 32 new tender matches based on your keywords: ball_valve, gate_valve

     Top Matched Tenders:
     ┌────────────────────────────────────────────────┐
     │ 1. Valve procurement for BHEL                  │
     │    Value: ₹5,00,000                           │
     │    Deadline: 2024-03-10                        │
     │    Matched Keywords: ball_valve (Conf: 92%)   │
     │    [View Full Tender]                         │
     ├────────────────────────────────────────────────┤
     │ 2. High pressure valve supply for ONGC        │
     │    Value: ₹12,00,000                          │
     │    Deadline: 2024-03-15                        │
     │    Matched Keywords: gate_valve (Conf: 88%)   │
     │    [View Full Tender]                         │
     │ ... (30 more tenders)                         │
     └────────────────────────────────────────────────┘

     Login to portal: [Link to TenderGyan dashboard]
     Next update: Tomorrow at 4:00 AM UTC

     Best Regards,
     TenderGyan Team
     ```

   **Step E: Send email**
   - Connect to SMTP server (Gmail / SendGrid / custom SMTP)
   - Send email to: procurement@org-a.com
   - Include all 32 tenders in HTML table format
   - Track email metadata:
     ```
     {
       recipient: "procurement@org-a.com",
       config_id: "valve-config",
       org_id: "org-a-id",
       tender_count: 32,
       sent_at: 2024-03-01 04:00:00,
       status: "SUCCESS" / "FAILED"
     }
     ```

   **Step F (SUCCESS): Mark tenders as emailed**
   - If SMTP sends successfully (status 250 OK):
     - Update `matched_tenders` table:
       ```
       UPDATE matched_tenders
       SET email_sent=TRUE, email_sent_at=NOW()
       WHERE config_id='valve-config'
       AND org_id='org-a-id'
       AND email_sent=FALSE
       ```
     - Log: "Email sent successfully for Org A: 32 tenders to procurement@org-a.com"

   **Step F (FAILURE): Retry email sending**
   - If SMTP fails (timeout, connection refused, Invalid recipient):
     - Log error: "Email send failed for Org A: {error_message}"
     - Retry logic:
       - Retry Attempt 1: Immediate retry
       - Retry Attempt 2: Retry after 5 minutes
       - Retry Attempt 3: Retry after 10 minutes
       - If all 3 retries fail:
         - Alert admin: "Email delivery failed after 3 attempts to procurement@org-a.com"
         - Email marked as failed but tenders NOT marked as email_sent
         - Will retry again on next scheduled time (tomorrow 4:00 AM)

3. **Later: 5:00 AM - Process Org B email**
   - Same process as Org A but:
     - Check Phase 2 for Org B 'Valve'
     - Fetch 28 matched tenders for Org B
     - Send to: operations@org-b.com
     - Update matched_tenders for Org B

**Example Full Scenario**:
```
3:25 AM: Phase 2 completes for Org B
        Both Org A (32 tenders) and Org B (28 tenders) ready
        ↓
4:00 AM: Email scheduled for Org A (procurement@org-a.com)
        Check Phase 2 status: 'Completed' ✓
        Fetch 32 matched tenders
        Send email with all 32 tenders
        Mark all 32 as email_sent=TRUE
        ↓
4:05 AM: Email sent successfully to Org A
        ↓
5:00 AM: Email scheduled for Org B (operations@org-b.com)
        Check Phase 2 status: 'Completed' ✓
        Fetch 28 matched tenders
        Send email with all 28 tenders
        Mark all 28 as email_sent=TRUE
        ↓
5:05 AM: Email sent successfully to Org B
        ↓
CYCLE COMPLETE:
- Phase 1: Downloaded 245 tenders ONCE
- Phase 2: Analyzed 245 tenders ONCE, but split results per org
- Phase 3: Sent personalized emails to each org at their scheduled time
```

**Database State After Phase 3**:
```
matched_tenders table (UPDATED):
├─ 32 rows for Org A
│  └─ email_sent: TRUE, email_sent_at: 2024-03-01 04:00:23
│
└─ 28 rows for Org B
   └─ email_sent: TRUE, email_sent_at: 2024-03-01 05:00:15

Email Log (if tracked):
├─ Org A, procurement@org-a.com, 32 tenders, status='SUCCESS', sent_at=04:00:23
└─ Org B, operations@org-b.com, 28 tenders, status='SUCCESS', sent_at=05:00:15
```

---

**Key Benefits of This 3-Phase Architecture**:

| Benefit | How it Works |
|---------|------------|
| **No duplicate downloads** | Phase 1 runs once per config, not per org |
| **Efficient analysis** | Phase 2 runs once per org-config pair (not per org separately) |
| **Flexible scheduling** | Each phase has independent time scheduling |
| **Dependency management** | Phase 2 waits for Phase 1, Phase 3 waits for Phase 2 |
| **Org-specific customization** | Each org has own keywords and email times in Phase 2 & 3 |
| **Graceful degradation** | If Phase 1 fails, Phase 2 retries; if Phase 2 fails, Phase 3 skips |
| **Audit trail** | Every execution tracked in `gem_search_task_execution` |
| **Scale horizontally** | Add more orgs without increasing download overhead |

---

## 9. Data Model

### 9.1. Logical Data Model

#### **New Tables**

**1. gem_org_search_capabilities**
```
Purpose: Store organization-specific matching keywords and execution times for shared configurations

Columns:
├─ capability_id (UUID, Primary Key)
├─ org_id (FK to organizations)
├─ config_id (FK to gem_search_configurations)
├─ matching_keywords (TEXT, comma-separated or JSON)
│  Example: "valve,pump,bearing" or "check_valve,ball_valve"
├─ phase_2_execution_time (VARCHAR, HH:MM format)
│  Example: "03:00" (3 AM UTC)
├─ is_active (BOOLEAN, default True)
├─ created_at (TIMESTAMP)
├─ updated_at (TIMESTAMP)
├─ created_by (FK to users, superadmin ID)
└─ updated_by (FK to users, superadmin ID)

Constraints:
├─ UNIQUE(org_id, config_id) - one capability per org per config
└─ Foreign Keys:
   ├─ org_id → organizations.id
   └─ config_id → gem_search_configurations.id
```

**2. gem_search_task_execution**
```
Purpose: Track execution status of Phase 1 (Download) and Phase 2 (Analysis) jobs

Columns:
├─ execution_id (UUID, Primary Key)
├─ config_id (FK to gem_search_configurations)
├─ org_id (FK to organizations, NULL for Phase 1)
├─ phase (ENUM: 'DOWNLOAD', 'ANALYSIS')
├─ status (ENUM: 'Not Started Yet', 'Running', 'Completed', 'Failed')
├─ started_at (TIMESTAMP)
├─ completed_at (TIMESTAMP, nullable)
├─ error_message (TEXT, nullable)
├─ retry_count (INTEGER, default 0)
├─ tenders_processed (INTEGER, nullable)
├─ tenders_matched (INTEGER, nullable)
├─ created_at (TIMESTAMP)
└─ updated_at (TIMESTAMP)

Constraints:
├─ Foreign Keys:
│  ├─ config_id → gem_search_configurations.id
│  └─ org_id → organizations.id (nullable)
└─ UNIQUE(config_id, org_id, phase, DATE(started_at))
   (one execution per config per org per phase per day)
```

**3. gem_org_email_mappings**
```
Purpose: Store organization-specific email recipients and their email send times

Columns:
├─ mapping_id (UUID, Primary Key)
├─ org_id (FK to organizations)
├─ config_id (FK to gem_search_configurations)
├─ email_address (VARCHAR, encrypted in database)
├─ email_send_time (VARCHAR, HH:MM format)
│  Example: "04:00" (4 AM UTC)
├─ is_active (BOOLEAN, default True)
├─ created_at (TIMESTAMP)
├─ updated_at (TIMESTAMP)
├─ created_by (FK to users)
└─ updated_by (FK to users)

Constraints:
├─ Foreign Keys:
│  ├─ org_id → organizations.id
│  ├─ config_id → gem_search_configurations.id
│  ├─ created_by → users.id
│  └─ updated_by → users.id
└─ Multiple emails per org per config allowed
```

#### **Modified Tables**

**1. gem_search_configurations**
```
Current Columns:
├─ config_id (UUID, Primary Key)
├─ config_name (VARCHAR) - e.g., "Valve", "Conveyor"
├─ search_keyword (VARCHAR)
├─ created_at (TIMESTAMP)
└─ updated_at (TIMESTAMP)

NEW Columns:
├─ phase_1_execution_time (VARCHAR, HH:MM format)
│  Example: "02:00" (2 AM UTC)
├─ created_by (FK to users, superadmin ID)
├─ updated_by (FK to users, superadmin ID)
├─ is_active (BOOLEAN, default True)
├─ description (TEXT, optional)
└─ search_filters (JSON, optional)
   Example: {"min_value": 1000, "max_value": 100000, "tender_type": "open"}

Note: Remove org_id if present (now shared across orgs)
```

#### **Entity Relationship Diagram (Logical)**

```
gem_search_configurations (Master)
    │
    ├─── 1:N ─── gem_org_search_capabilities (Org-specific Keywords)
    │                │
    │                └─── 1:N ─── gem_org_email_mappings (Email Recipients)
    │
    └─── 1:N ─── gem_search_task_execution (Phase 1 & 2 Status Tracking)

organizations
    │
    ├─── 1:N ─── gem_org_search_capabilities
    │
    └─── 1:N ─── gem_org_email_mappings

tenders (existing)
    └─ Add column: config_id (FK to gem_search_configurations)

matched_tenders (existing or new)
    └─ Columns:
       ├─ match_id (PK)
       ├─ tender_id (FK to tenders)
       ├─ config_id (FK to gem_search_configurations)
       ├─ org_id (FK to organizations)
       ├─ matched_keywords (TEXT or JSON)
       ├─ confidence_score (DECIMAL)
       ├─ email_sent (BOOLEAN, default False)
       ├─ created_at (TIMESTAMP)
       └─ updated_at (TIMESTAMP)
```

### 9.2. Storage Considerations

**Transactional Data**:
- `gem_search_configurations`: Master data (low churn, read-heavy)
- `gem_org_search_capabilities`: Organization-specific config (medium churn)
- `gem_org_email_mappings`: Email addresses and schedules (medium churn)
- `gem_search_task_execution`: Task execution history (write-heavy during scheduled times)
- `matched_tenders`: Analysis results (write-heavy during Phase 2)

**Retention Policy**:
- `gem_search_task_execution`: Keep for 90 days (for audit and debugging)
- `matched_tenders`: Keep until email sent + 30 days (for delivery confirmation)
- `gem_search_configurations`, `gem_org_search_capabilities`, `gem_org_email_mappings`: Retain indefinitely (soft delete via is_active flag)

**Backup Strategy**:
- Daily backups of entire database
- Backup frequency: Every 6 hours for production
- Retention: 30 days of automated backups, 1 year of manual monthly backups

### 9.3. Migration & Backward Compatibility

**Schema Changes**:

1. **Add execution time columns to `gem_search_configurations`**:
   ```sql
   ALTER TABLE gem_search_configurations
   ADD COLUMN phase_1_execution_time VARCHAR(5) DEFAULT '02:00';

   ALTER TABLE gem_search_configurations
   ADD COLUMN created_by UUID REFERENCES users(id);

   ALTER TABLE gem_search_configurations
   ADD COLUMN updated_by UUID REFERENCES users(id);

   ALTER TABLE gem_search_configurations
   ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
   ```

2. **Create new tables**:
   ```sql
   CREATE TABLE gem_org_search_capabilities (...)
   CREATE TABLE gem_search_task_execution (...)
   CREATE TABLE gem_org_email_mappings (...)
   ```

3. **Add config_id to `tenders` table** (if not present):
   ```sql
   ALTER TABLE tenders
   ADD COLUMN config_id UUID REFERENCES gem_search_configurations(config_id);
   ```

4. **Migrate existing org-level configurations to new structure**:
   ```
   FOR EACH search_config in OLD system:
       1. Create master config in gem_search_configurations
       2. Create capability in gem_org_search_capabilities for each org
       3. Create email mapping in gem_org_email_mappings for each email
   ```

**Backward Compatibility**:
- Old org-specific configurations in `gem_search_configurations` (if they exist) remain intact
- New code reads from both old and new structure during transition period
- Flag: `use_shared_config = True/False` in config to enable/disable new flow per organization
- Once all orgs migrated, phase out old code (version 2.0)

**Rollback Strategy**:
- Keep historical data in separate tables (`_legacy` suffix)
- If rollback needed:
  1. Revert database schema
  2. Restore from backup
  3. Switch scheduler to old logic
  4. Manual email re-send for any missed notifications

### 9.4. SQL

#### **Table Creation Scripts**

```sql
-- Create gem_org_search_capabilities table
CREATE TABLE gem_org_search_capabilities (
    capability_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    config_id UUID NOT NULL REFERENCES gem_search_configurations(config_id) ON DELETE CASCADE,
    matching_keywords TEXT NOT NULL COMMENT 'Comma-separated keywords, e.g., "valve,pump,bearing"',
    phase_2_execution_time VARCHAR(5) NOT NULL DEFAULT '03:00' COMMENT 'HH:MM format, UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by UUID NOT NULL REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    UNIQUE KEY unique_org_config (org_id, config_id),
    FOREIGN KEY (org_id) REFERENCES organizations(id),
    FOREIGN KEY (config_id) REFERENCES gem_search_configurations(config_id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id),
    INDEX idx_org_id (org_id),
    INDEX idx_config_id (config_id),
    INDEX idx_execution_time (phase_2_execution_time)
);

-- Create gem_search_task_execution table
CREATE TABLE gem_search_task_execution (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id UUID NOT NULL REFERENCES gem_search_configurations(config_id) ON DELETE CASCADE,
    org_id UUID REFERENCES organizations(id) ON DELETE CASCADE COMMENT 'NULL for Phase 1, populated for Phase 2',
    phase ENUM('DOWNLOAD', 'ANALYSIS') NOT NULL,
    status ENUM('Not Started Yet', 'Running', 'Completed', 'Failed') NOT NULL DEFAULT 'Not Started Yet',
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    error_message TEXT NULL,
    retry_count INT NOT NULL DEFAULT 0,
    tenders_processed INT NULL,
    tenders_matched INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (config_id) REFERENCES gem_search_configurations(config_id),
    FOREIGN KEY (org_id) REFERENCES organizations(id),
    UNIQUE KEY unique_execution (config_id, org_id, phase, DATE(started_at)),
    INDEX idx_config_phase (config_id, phase),
    INDEX idx_status_phase (status, phase),
    INDEX idx_execution_time (started_at),
    INDEX idx_org_phase (org_id, phase)
);

-- Create gem_org_email_mappings table
CREATE TABLE gem_org_email_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    config_id UUID NOT NULL REFERENCES gem_search_configurations(config_id) ON DELETE CASCADE,
    email_address VARCHAR(255) NOT NULL COMMENT 'Should be encrypted at application level',
    email_send_time VARCHAR(5) NOT NULL COMMENT 'HH:MM format, UTC',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by UUID NOT NULL REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    FOREIGN KEY (org_id) REFERENCES organizations(id),
    FOREIGN KEY (config_id) REFERENCES gem_search_configurations(config_id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (updated_by) REFERENCES users(id),
    INDEX idx_org_config (org_id, config_id),
    INDEX idx_email_send_time (email_send_time),
    INDEX idx_is_active (is_active)
);

-- Alter gem_search_configurations to add new columns
ALTER TABLE gem_search_configurations
ADD COLUMN phase_1_execution_time VARCHAR(5) NOT NULL DEFAULT '02:00' COMMENT 'HH:MM format, UTC',
ADD COLUMN created_by UUID REFERENCES users(id),
ADD COLUMN updated_by UUID REFERENCES users(id),
ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE,
ADD COLUMN description TEXT,
ADD COLUMN search_filters JSON;

-- Add indexes for execution time queries
CREATE INDEX idx_phase_1_execution_time ON gem_search_configurations(phase_1_execution_time);
CREATE INDEX idx_search_config_active ON gem_search_configurations(is_active, phase_1_execution_time);

-- Add config_id to tenders table (if not present)
ALTER TABLE tenders
ADD COLUMN config_id UUID REFERENCES gem_search_configurations(config_id);

-- Add indexes for tender queries
CREATE INDEX idx_tenders_config_id ON tenders(config_id);
CREATE INDEX idx_tenders_config_created ON tenders(config_id, created_at);
```

#### **Key Queries**

```sql
-- Query 1: Get all Phase 1 jobs to execute at current time
SELECT * FROM gem_search_configurations
WHERE is_active = TRUE
AND phase_1_execution_time = TIME_FORMAT(NOW(), '%H:%i');

-- Query 2: Get Phase 1 status for a config
SELECT status, completed_at, error_message
FROM gem_search_task_execution
WHERE config_id = ?
AND phase = 'DOWNLOAD'
AND DATE(started_at) = CURDATE()
ORDER BY started_at DESC LIMIT 1;

-- Query 3: Get all Phase 2 jobs to execute and check Phase 1 dependency
SELECT gsc.*, gosb.*
FROM gem_org_search_capabilities gosb
JOIN gem_search_configurations gsc ON gosb.config_id = gsc.config_id
WHERE gosb.is_active = TRUE
AND gosb.phase_2_execution_time = TIME_FORMAT(NOW(), '%H:%i');

-- Query 4: Get matched tenders for email sending
SELECT mt.*, gsc.config_name, o.org_name
FROM matched_tenders mt
JOIN gem_search_configurations gsc ON mt.config_id = gsc.config_id
JOIN organizations o ON mt.org_id = o.id
JOIN gem_org_email_mappings gem ON gem.org_id = mt.org_id AND gem.config_id = mt.config_id
WHERE gem.email_send_time = TIME_FORMAT(NOW(), '%H:%i')
AND gem.is_active = TRUE
AND mt.email_sent = FALSE
ORDER BY mt.created_at DESC;

-- Query 5: Check if Phase 2 analysis already completed today
SELECT status FROM gem_search_task_execution
WHERE config_id = ?
AND org_id = ?
AND phase = 'ANALYSIS'
AND DATE(started_at) = CURDATE()
LIMIT 1;
```

---

## 10. UI Solution

### 10.1. Application Process Flow

#### **Superadmin Portal: Configuration Management**

**Page 1: Shared Search Configurations**
- List all master configurations ('Valve', 'Conveyor', etc.)
- Create new configuration:
  - Input: Configuration name, search keyword, Phase 1 execution time (HH:MM), description, filters
  - Action: Save to `gem_search_configurations`
- Edit configuration:
  - Update name, keyword, Phase 1 time, filters
  - Show linked organizations count
  - Action: Update database
- View execution history:
  - Show Phase 1 execution logs (last 30 days)
  - Filter by status: 'Completed', 'Failed'
  - Action: Download logs

**Page 2: Organization Management (per Org)**
- Superadmin can:
  - Assign configurations to organization (link org to config)
  - Set Phase 2 execution time per org
  - Define matching keywords per org
  - Manage email recipients and send times
  - Enable/disable capability or email mapping

### 10.2. Page Process/Navigation Flow

#### **Flow 1: Superadmin Creates Master Configuration**
```
1. Navigate to "Shared Configurations" → "Create Configuration"
2. Form: Configuration name, search keyword, Phase 1 time, filters, description
3. Click "Create"
4. Validate and save to gem_search_configurations
5. Show success message: "Configuration 'Valve' created. Phase 1 scheduled for 2:00 AM UTC."
6. Redirect to configuration details page
```

#### **Flow 2: Organization Links to Configuration and Sets Keywords**
```
1. Superadmin navigates to "Organization Management" → Select Org → "Add Configuration"
2. Dropdown: Select from available configurations
3. Input: Phase 2 execution time, matching keywords
4. Click "Link Configuration"
5. Validate and save to gem_org_search_capabilities
6. Show success: "Configuration linked. Analysis scheduled for 3:00 AM UTC."
7. Now admin can set email recipients
```

#### **Flow 3: Organization Sets Email Recipients and Send Times**
```
1. From org config page, click "Add Email Recipient"
2. Form: Email address, email send time (HH:MM)
3. Click "Add"
4. Validate and save to gem_org_email_mappings
5. Show list of email recipients with their send times
6. Option to edit/delete recipient
```

#### **Flow 4: Monitor Execution Status**
```
1. Superadmin navigates to "Execution Monitor" (dashboard)
2. Display:
   - Phase 1 status for each configuration (today's execution)
   - Phase 2 status for each org-config pair
   - Email delivery log for last 24 hours
3. Filter by status, date range, configuration
4. View detailed logs with error messages
5. Manual actions: Retry Phase 1, Skip Phase 2, Re-send email
```

### 10.3. UI Components

#### **New Components**

1. **Configuration Form Component**
   - Inputs: Name, keyword, execution time picker, filter JSON editor
   - Validation: Unique name, valid time format (HH:MM)
   - Save/Cancel buttons

2. **Capability Form Component**
   - Inputs: Matching keywords (text area), Phase 2 execution time
   - Multi-line keywords support
   - Save/Cancel buttons

3. **Email Mapping Component**
   - Add/Edit email form: Email address, send time
   - List of recipients with edit/delete actions
   - Encryption warning for email storage

4. **Execution Status Card**
   - Status badge: 'Running', 'Completed', 'Failed', 'Pending'
   - Timeline: Started at, completed at, duration
   - Error details (if failed)
   - Retry button (if failed)

5. **Execution Monitor Dashboard**
   - Grid view of all Phase 1 executions (today)
   - Grid view of all Phase 2 executions (today)
   - Email delivery log table
   - Filter dropdowns: Configuration, Organization, Status, Date range
   - Charts: Execution success rate, avg execution time, emails sent

#### **Modified Components**

1. **Organization Management Page**
   - Add "Configurations" section showing linked shared configurations
   - Add "Email Recipients" section for management
   - Previously: Only org-specific search configs

2. **Admin Dashboard**
   - Add execution status widget showing health of Phase 1/2/3
   - Alert section: Highlight failed executions

---

## 11. Non-Functional Requirements

| Category | Requirement | Technical Details |
|----------|-------------|-------------------|
| **Performance** | Phase 1 execution time | < 30 mins per 1000 tenders (GeM API dependent) |
| | Phase 2 execution time | < 10 mins per 1000 tenders (NLP analysis) |
| | Phase 3 email send time | < 5 mins per 100 recipients |
| | Database query response time | < 500ms for execution status checks |
| **Scalability** | Concurrent Phase 1 jobs | Support 10+ parallel configurations |
| | Organizations per config | Support 100+ organizations per shared config |
| | Email recipients per org | Support 50+ email recipients per org |
| | Tender volume | Support 10,000+ tenders per day |
| **Reliability** | Uptime | 99.5% availability for scheduler and database |
| | Data durability | 99.999% (multiple backups, transaction support) |
| | Retry mechanism | Exponential backoff for failed Phase 1 jobs (max 5 retries) |
| | Email delivery | Retry up to 3 times on SMTP failure |
| **Security** | Email encryption | AES-256 encryption at rest in database |
| | Access control | Role-based (Superadmin > Org Admin > User) |
| | Data privacy | GDPR compliant; no personal data in logs |
| | API security | Rate limiting on external API calls (GeM) |
| **Cost** | LLM usage | Budget ₹X per day for NLP analysis |
| | Database storage | Optimize query performance; archive old execution logs |
| | Email sending | Batch email sending to reduce SMTP overhead |

---

## 12. System Integration and Monitoring

### 12.1. Process Execution and Scheduling

**Scheduler Implementation** (Enhanced `gem_scheduler.py` using APScheduler):

```python
# Pseudo-code
scheduler = APScheduler()

# Phase 1: Download scheduled jobs
for config in fetch_all_active_configs():
    phase_1_time = config.phase_1_execution_time  # e.g., "02:00"
    scheduler.add_job(
        func=phase_1_download,
        trigger="cron",
        hour=phase_1_time.split(':')[0],
        minute=phase_1_time.split(':')[1],
        args=[config.id],
        id=f"phase1_config_{config.id}",
        replace_existing=True
    )

# Phase 2: Analysis scheduled jobs (depends on Phase 1)
for capability in fetch_all_active_capabilities():
    phase_2_time = capability.phase_2_execution_time  # e.g., "03:00"
    scheduler.add_job(
        func=phase_2_analyze,
        trigger="cron",
        hour=phase_2_time.split(':')[0],
        minute=phase_2_time.split(':')[1],
        args=[capability.org_id, capability.config_id],
        id=f"phase2_org_{capability.org_id}_config_{capability.config_id}",
        replace_existing=True
    )

# Phase 3: Email scheduled jobs (depends on Phase 2)
for mapping in fetch_all_active_email_mappings():
    email_time = mapping.email_send_time  # e.g., "04:00"
    scheduler.add_job(
        func=phase_3_send_email,
        trigger="cron",
        hour=email_time.split(':')[0],
        minute=email_time.split(':')[1],
        args=[mapping.org_id, mapping.config_id, mapping.email_address],
        id=f"phase3_email_{mapping.mapping_id}",
        replace_existing=True
    )

scheduler.start()
```

**Job Recovery**:
- On app restart, scheduler reloads all active jobs from database
- Failed jobs logged with error details
- Manual retry available from admin UI

### 12.2. Process Restartability

#### **Scenario 1: Phase 1 Fails**
- Status in `gem_search_task_execution`: 'Failed'
- Retry count incremented
- **Automatic Restart**: If retry_count < 5, job queued for 5 mins later
- **Manual Restart**: Superadmin clicks "Retry Phase 1" button on UI
- Action: Update status to 'Not Started Yet', reset retry_count

#### **Scenario 2: Phase 2 Waits for Phase 1**
- Phase 2 starts at scheduled time, checks Phase 1 status
- If Phase 1 not 'Completed', Phase 2 job queued for 5 mins later
- **Automatic Restart**: Up to 12 retries (1 hour total wait)
- **Manual Restart**: Superadmin forces Phase 2 to skip dependency check (admin option)

#### **Scenario 3: Email Fails to Send**
- SMTP failure logged
- **Automatic Retry**: 3 attempts with 10-min intervals
- **Manual Retry**: Superadmin re-sends email from UI
- Action: Reset `matched_tenders.email_sent = FALSE`

#### **Scenario 4: System Crash During Execution**
- On recovery, scheduler checks database for incomplete jobs
- If Phase 1 was 'Running' for > 1 hour, mark as 'Failed' and retry
- If Phase 2 was 'Running' for > 30 mins, mark as 'Failed' and retry
- Log: "Job recovery: Phase X restarted after crash"

---

## 13. Error Management

### 13.1. Error Logging

**Log Storage**:
- Format: JSON (structured logging for easy parsing)
- Location: File-based logs in `/logs/gem_scheduler.log` and `/logs/gem_nlp_api.log`
- Rotation: Daily rotation; keep 30 days of logs
- Also: Store errors in database table `error_logs` for UI visibility

**Error Log Fields**:
```json
{
  "timestamp": "2026-03-01T02:15:00Z",
  "level": "ERROR",
  "phase": "PHASE_1",
  "config_id": "uuid-xxx",
  "org_id": "uuid-yyy",
  "error_code": "SCRAPE_TIMEOUT",
  "error_message": "GeM API timeout after 5 retries",
  "stacktrace": "...",
  "user": "admin@tendergyan.com",
  "action": "Scheduled job execution"
}
```

**Error Categories**:

| Error Code | Description | Handling |
|-----------|-------------|----------|
| SCRAPE_TIMEOUT | GeM website not responding | Retry Phase 1 after 5 mins |
| SCRAPE_NO_RESULTS | No tenders found for keyword | Log warning; continue (OK) |
| NLP_API_ERROR | LLM service unavailable | Retry Phase 2 after 5 mins |
| DB_CONNECTION_ERROR | Database connection lost | Retry; alert admin |
| EMAIL_SMTP_ERROR | SMTP server error | Retry 3 times; alert admin |
| INVALID_EMAIL | Email address invalid | Skip; log warning; don't retry |
| PHASE_1_NOT_COMPLETED | Phase 1 still running when Phase 2 starts | Retry Phase 2 after 5 mins |
| CONFIG_NOT_FOUND | Configuration ID not found | Skip job; alert admin |
| DUPLICATE_EXECUTION | Phase already running | Skip; log warning |

### 13.2. Alerts and Notifications

**Alert Triggers**:

| Condition | Severity | Alert Type | Sent To | Description |
|-----------|----------|-----------|---------|------------|
| Phase 1 fails after 5 retries | HIGH | Email + Dashboard | Superadmin | "Phase 1 failed for config '{config_name}'. Manual intervention required." |
| Phase 2 waits > 1 hour for Phase 1 | MEDIUM | Email | Superadmin | "Phase 2 for org '{org_name}' waiting > 1 hour. Phase 1 may be stuck." |
| Email send fails after 3 retries | MEDIUM | Email + Dashboard | Superadmin, Org Admin | "Email not delivered to {email_address}. Check SMTP settings." |
| Database connection lost | CRITICAL | Email + SMS | DevOps, Superadmin | "Database connection lost. Scheduler may stop." |
| Scheduler process stopped | CRITICAL | Email + SMS | DevOps | "Scheduler process stopped. No jobs will execute." |
| Zero tenders found in Phase 1 | LOW | Dashboard only | Superadmin | "Phase 1 for '{config_name}' completed with 0 tenders." |
| Phase 1 execution > 1 hour | MEDIUM | Dashboard | Superadmin | "Phase 1 took longer than expected (60+ mins)." |

---

## 14. Security & Governance

### 14.1. Access Control

**Role-Based Access Control (RBAC)**:

| Role | Module | Permissions |
|------|--------|------------|
| **Superadmin** | Shared Configurations | Create, Read, Update, Delete, View execution logs |
| | Organization Management | Assign configs, set keywords, manage emails, view org-specific logs |
| | Execution Monitor | View all Phase 1/2/3 logs, manual retry, force skip |
| **Org Admin** | Own Org Configurations | View assigned configs, manage matching keywords, manage email recipients |
| | Execution Monitor | View own Phase 2/3 logs only |
| **Org User** | Own Org Configurations | View assigned configs and email recipients (read-only) |

**API Access Control**:
- Superadmin token required for master config endpoints
- Org admin token required for org-specific endpoints
- User roles verified before every database operation

### 14.2. Data Privacy & Compliance

**Email Encryption**:
- All email addresses encrypted with AES-256 before storing in `gem_org_email_mappings`
- Decrypted only during email sending phase
- Key stored in environment variables (never in code or database)

**Data Retention**:
- `gem_search_task_execution`: Keep 90 days; auto-delete older records
- `matched_tenders`: Keep until email sent + 30 days
- `error_logs`: Keep 30 days; auto-delete older records
- Soft delete: is_active flag for permanent data (configs, capabilities, mappings)

**GDPR Compliance**:
- Email addresses collected via admin consent (documented in terms)
- Right to erasure: Superadmin can delete org's email mappings (triggers data deletion)
- Data processing agreement in place with any external email services

**Audit Trail**:
- All configuration changes logged with user ID and timestamp
- Columns: `created_by`, `updated_by`, `created_at`, `updated_at` on all tables
- Sensitive field changes (email) logged separately to audit_logs table

---

## 15. Version Control and Coding Standards

**Version Control Tool**: Git (hosted on GitHub/GitLab)

**Branching Strategy**:
- Main branch: `main` (production-ready code, protected)
- Development branch: `develop` (integration branch)
- Feature branches: `feature/shared-configurations` (from `develop`)
- Hotfix branches: `hotfix/issue-xyz` (from `main`)

**Commit Message Format**:
```
[PHASE1|PHASE2|PHASE3] Brief description

Detailed description if needed.

Related to issue #XXX
```

**Code Review Process**:
- Minimum 2 approvals before merge to `develop`
- Minimum 1 approval + CI/CD passing before merge to `main`
- Automated checks: Linting, unit tests, type checking (mypy for Python)

**Coding Standards**:
- **Python**: PEP 8, Black formatter (line length 99), type hints on all functions
- **SQL**: Snake_case for table/column names, comments on complex queries
- **Documentation**: Docstrings on all functions, README for setup instructions
- **Logging**: Structured logging (JSON format) at EVERY major step
- **Error Handling**: Explicit exception handling; no silent failures

**Test Coverage**:
- Unit tests: Minimum 80% coverage for new code
- Integration tests: Phase 1, 2, 3 end-to-end scenarios
- Test database: Separate SQLite instance for testing

---

## 16. System Policies

### 16.1. Security / Governance

**Data Security**:
- All database access via ORM (SQLAlchemy) to prevent SQL injection
- Input validation on all user-facing forms
- Rate limiting on API endpoints (10 requests/min per IP)
- Log rotation to prevent unbounded disk growth

**Application Security**:
- HTTPS-only communication
- CORS configured to allow only trusted domains
- CSRF tokens on all state-changing forms
- Session timeout: 15 minutes of inactivity
- Password policy: Min 12 chars, uppercase, lowercase, number, special char

**Operational Security**:
- Superadmin credentials stored in password manager (1Password/Vault)
- Scheduler process runs under non-root user
- Database backups encrypted and stored in secure cloud storage
- Access logs to sensitive operations (config changes) retained for audit

### 16.2. Data Quality

**Configuration Validation**:
- Config name: Non-empty, unique across all superadmins
- Search keyword: Non-empty, evaluated for keyword overlap between configs
- Execution times: Must be valid HH:MM format (00:00 to 23:59)
- Matching keywords: CSV or JSON format validation

**Data Completeness**:
- All tenders must have: tender_id, title, description, source_url, config_id
- All matched_tenders must have: tender_id, keyword, confidence_score
- All executions must have: status, started_at, completed_at (if status = Completed)

**Data Reconciliation** (Daily):
- Count tenders downloaded vs tenders matched (should be consistent)
- Count emails scheduled vs emails sent (should be consistent by EOD)
- Check for orphaned records (tenders with invalid config_id)

**Issue Resolution**:
- Data quality issues logged to `data_quality_issues` table
- Superadmin notified daily of issues
- Manual correction possible via admin UI

---

## 17. References

- Apache APScheduler Documentation: https://apscheduler.readthedocs.io/
- Flask Documentation: https://flask.palletsprojects.com/
- SQLAlchemy ORM Documentation: https://docs.sqlalchemy.org/
- GeM API Documentation: (Internal or external link)
- OWASP Top 10 Security Risks: https://owasp.org/www-project-top-ten/
- PEP 8 Python Style Guide: https://www.python.org/dev/peps/pep-0008/
- JSON Structured Logging Best Practices: https://www.json.org/

---

## 18. Appendix

### Email Notification Template

**Phase 1 Failure Alert**:
```
Subject: [TenderGyan Alert] Phase 1 Download Failed - {config_name}

Dear Superadmin,

Phase 1 (Download) for configuration "{config_name}" failed after 5 retries.

Details:
- Configuration: {config_name}
- Search Keyword: {keyword}
- Scheduled Time: {phase_1_execution_time}
- Error: {error_message}
- Last Attempt: {last_attempted_at}

Action Required:
1. Check GeM website availability
2. Review error logs: /logs/gem_scheduler.log
3. Click below to retry manually: [RETRY BUTTON]

Support: contact@tendergyan.com
```

**Phase 2 Completion Email** (Org Admin):
```
Subject: Tender Analysis Complete - {config_name} ({matched_count} matches)

Dear {org_admin_name},

Analysis for "{config_name}" configuration is complete.

Summary:
- Configuration: {config_name}
- Total Tenders Downloaded: {total_count}
- Matched Tenders: {matched_count}
- Your Keywords: {matching_keywords}

Next Steps:
Your matched tenders will be delivered to {recipient_email} at {email_send_time} UTC.

View details: [LINK to matched tenders]
```

**Phase 3 Email** (Org Recipient):
```
Subject: New {config_name} Tenders - {matched_count} Matches Today

Dear {recipient_name},

We found {matched_count} new tenders matching your keywords:

[TABLE of matched tenders with details]

Actions:
- View Full Tender: [Link per tender]
- Download as PDF: [Link]
- View Supplier Profile: [Link]

Next Update: {next_email_send_time} UTC

Questions: support@tendergyan.com
```

### Sample Configuration

**Example 1: Valve Configuration**
```json
{
  "config_id": "uuid-valve-001",
  "config_name": "Valve",
  "search_keyword": "valve",
  "phase_1_execution_time": "02:00",
  "search_filters": {
    "tender_type": "open",
    "min_value": 10000,
    "max_value": 5000000
  },
  "created_by": "superadmin@tendergyan.com",
  "is_active": true
}
```

**Example 2: Organization Linking**
```json
{
  "capability_id": "uuid-cap-001",
  "org_id": "uuid-org-valve-makers",
  "config_id": "uuid-valve-001",
  "matching_keywords": "ball_valve,check_valve,gate_valve,butterfly_valve",
  "phase_2_execution_time": "03:00",
  "created_by": "superadmin@tendergyan.com",
  "is_active": true
}
```

**Example 3: Email Mapping**
```json
{
  "mapping_id": "uuid-email-001",
  "org_id": "uuid-org-valve-makers",
  "config_id": "uuid-valve-001",
  "email_address": "procurement@valvemakers.com",
  "email_send_time": "04:00",
  "is_active": true,
  "created_by": "admin@valvemakers.com"
}
```

---

**End of Technical Specifications Document**
