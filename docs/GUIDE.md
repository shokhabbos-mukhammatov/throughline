# Throughline: run, test and deploy

One guide, top to bottom. Commands are for macOS and Linux; on Windows use WSL or Git Bash.

- [1. Set up once](#1-set-up-once)
- [2. Run it locally](#2-run-it-locally)
- [3. Test it](#3-test-it)
- [4. Deploy to Google Cloud](#4-deploy-to-google-cloud)
- [5. Ship updates](#5-ship-updates)
- [6. When something goes wrong](#6-when-something-goes-wrong)
- [7. Demo day](#7-demo-day)

---

## 1. Set up once

**You need**

| Tool | Version | Needed for |
|---|---|---|
| git | any | everything |
| Python | 3.11 or newer | the backend |
| Node.js | 20 or newer (22 recommended) | the frontend |
| Gemini API key | from https://aistudio.google.com → Get API key | real syllabi (without it, the app runs in offline mode) |
| Java | 11 or newer | only for the Firestore emulator test |
| Docker | any | only to test the production image locally |
| gcloud CLI | latest | only to deploy |

**Get the code and configure it**
```bash
git clone https://github.com/<owner>/<repo>.git
cd <repo>
cp .env.example .env
```
Open `.env` and paste your key after `GEMINI_API_KEY=`. Never commit `.env`; it is git-ignored.

**Install dependencies**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cd ../frontend
npm ci
cd ..
```

---

## 2. Run it locally

### Option A: development (two terminals, live reload)

**Terminal 1, backend** (from the repo root):
```bash
cd backend
source .venv/bin/activate
set -a; source ../.env; set +a        # loads GEMINI_API_KEY and the other settings
uvicorn throughline.api:app --port 8080 --reload
```

**Terminal 2, frontend:**
```bash
cd frontend
npm run dev
```
Open **http://localhost:5173**. The frontend forwards `/api` to the backend on port 8080.

### Option B: one process (closest to production)
```bash
cd frontend && npm run build && cd ..
cd backend && source .venv/bin/activate && set -a && source ../.env && set +a
uvicorn throughline.api:app --port 8080
```
Open **http://localhost:8080**. The backend serves the built page and the API.

### Option C: the production container
```bash
docker build -t throughline .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY="$(grep ^GEMINI_API_KEY= .env | cut -d= -f2-)" throughline
```
Open **http://localhost:8080**.

### Check it's working
```bash
curl http://localhost:8080/api/health
```
You should see `"ok":true`. `"online":true` means Gemini is connected; `false` means offline mode (no key).

Locally the app stores data in `backend/.data/` and uses anonymous browser ids: no sign-in, no Google Cloud.

---

## 3. Test it

### Automated tests (about 1 minute)

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                    # expect: 60 passed, 1 skipped
```
The skipped test is the Firestore round trip. To run all 61 against the Firestore emulator (needs Java), as CI does:
```bash
npx firebase-tools emulators:exec --config ../firebase.json --only firestore --project demo-throughline "python -m pytest -q"
```
Frontend:
```bash
cd ../frontend
npm run typecheck && npm run build     # no errors expected
```

### Click-through test (5 minutes; do this before every demo)

Start the app (section 2), then in the browser:

1. **Sample course.** Home → **Try the sample course**.
   - Setup: pick "I took an equivalent course somewhere else", **3 h**, mark "Derivatives and the Chain Rule" as **Never**, then **Save and take the quick check**.
   - Quick check: each question shows *why* it was picked; answer a few. Each answer shows how the estimate moved, including for related concepts.
   - **My plan**: foundations come before what builds on them ("comes before …"); anything that can't fit appears under **Won't fit before it's needed**.
   - **Prerequisite map**: arrows from what you need first to what builds on it. Click a concept: its evidence quote and where to learn it.
   - **My notes**: upload slides or notes from the prerequisite (PDF, .pptx, .docx, text or a photo). In 5–30 seconds it lists which concepts they cover and on which slide or page; **My plan** then shows "Your notes · slide N" before the textbook links.
   - **Class view**: a simulated class, with cells hidden below 5 students. **Review map**: "How this map was built". **Share**: QR code.
2. **A real syllabus** (needs the Gemini key). Home → course number (e.g. `DS 612`) → upload the syllabus → **Map my course**. It takes about 1–2 minutes. Then check:
   - the timeline matches the syllabus;
   - the prerequisite map makes sense;
   - **Review map** shows about 20 model calls and no errors.
   - Remove weak concepts there before showing it to anyone.
3. **Phone.** Open the same page on your phone (or the browser's phone view): tabs scroll sideways and the map becomes a list.

### Quality checks with real syllabi (optional, about 2 minutes per course)

Real syllabi stay in `private/`, which is git-ignored. The file names must match `backend/eval/gold/*.json`: `csc411.txt`, `csc648.pdf`, `csc665.pdf`, `ds612.docx`, `math324.pdf`.
```bash
cd backend && source .venv/bin/activate && set -a && source ../.env && set +a
python scripts/try_syllabus.py "DS 612" ../private/ds612.docx --questions   # print the map for one syllabus
python scripts/evaluate.py --files ../private                              # score all against the gold labels
python scripts/check_links.py                                              # textbook links + live Bulletin
```
The gold labels in `backend/eval/gold/` are drafts. Correct them before quoting any score.

---

## 4. Deploy to Google Cloud

Project **sf-hacks-tutor** (number 96823963383). It will live at **https://throughline-96823963383.us-central1.run.app**.
You do this once; about 20 minutes. You need Owner on the Google Cloud project and admin on the GitHub repo.

### Step 1. Create the Google Cloud resources
```bash
gcloud auth login
gcloud config set project sf-hacks-tutor
GITHUB_REPO=<owner>/<repo> GEMINI_API_KEY="$(grep ^GEMINI_API_KEY= .env | cut -d= -f2-)" ./deploy/bootstrap.sh
```
This turns on the APIs and creates:
- Firestore and the image repository;
- the build queue;
- three service accounts with minimal permissions;
- keyless GitHub access;
- the Gemini key in Secret Manager.

It's safe to re-run. At the end it prints **five values**.

### Step 2. Give GitHub those values
GitHub repo → **Settings → Secrets and variables → Actions → Variables** tab → **New repository variable**, five times:

| Name | Value |
|---|---|
| `GCP_PROJECT_ID` | `sf-hacks-tutor` |
| `GCP_PROJECT_NUMBER` | `96823963383` |
| `GCP_REGION` | `us-central1` |
| `GCP_WIF_PROVIDER` | the long `projects/…/providers/github` value the script printed |
| `GCP_DEPLOY_SA` | `throughline-deployer@sf-hacks-tutor.iam.gserviceaccount.com` |

### Step 3. Turn on sign-in (optional; without it the app uses anonymous ids)
1. https://console.firebase.google.com → **Add project** → choose **sf-hacks-tutor**.
2. **Build → Authentication → Get started → Sign-in method**: enable **Anonymous**; enable **Google** (pick your email as the support email).
3. **Authentication → Settings → Authorized domains → Add domain**: `throughline-96823963383.us-central1.run.app`
4. **Project settings (gear) → Your apps → Web `</>`** → register an app (no Hosting). Copy `apiKey` and `appId`
   into two more GitHub variables: `FIREBASE_API_KEY` and `FIREBASE_APP_ID`.

### Step 4. Deploy
Merge the branch into `main` (a pull request on GitHub, or `git checkout main && git merge claude/admiring-mendel-ywhdpt && git push`).
Pushing to `main` starts **Actions → Deploy**, which:
1. tests;
2. builds the image;
3. deploys it;
4. checks the live site;
5. rolls back if that check fails.

It takes about 5–8 minutes. The run's summary shows the URL.

### Step 5. Check the live site
```bash
curl https://throughline-96823963383.us-central1.run.app/api/health
```
Expect `"ok":true`, `"online":true`, `"store":"firestore"` and `"queue":"cloudtasks"` in the response.
`/api/health?deep=1` also makes one tiny Gemini call and must show `"gemini":"ok"` (the deploy checks this too). Then do the click-through test (section 3) on the live URL, including on your phone over cellular. If you turned on sign-in, adding a course asks for Google; the QR join doesn't.

### Step 6. Turn on downtime alerts
```bash
ALERT_EMAIL=you@sfsu.edu ./deploy/monitoring.sh
```
Click the verification link Google emails you.

---

## 5. Ship updates

| I want to | Do this |
|---|---|
| Ship a change | Push to `main`; watch **Actions → Deploy** (green means live and checked). |
| Check a branch before merging | Push the branch: **Actions → CI** runs all tests and the image build. |
| Deploy a branch | **Actions → Deploy → Run workflow** → pick the branch. |
| Deploy without GitHub | `./deploy/deploy.sh` (same settings; builds in Cloud Build) |
| Change the Gemini key | `printf %s NEW_KEY \| gcloud secrets versions add gemini-api-key --data-file=-`, then redeploy |
| Before a demo | Don't push to `main` in the last hour. Build the demo course ahead and review it. |

---

## 6. When something goes wrong

| Symptom | What to do |
|---|---|
| "The AI service rejected this site's credentials" (live site) | The Gemini key in Secret Manager is wrong. In Cloud Shell: `read -rs K`, paste the key; check `curl -s -o /dev/null -w "%{http_code}\n" -H "x-goog-api-key: $K" https://generativelanguage.googleapis.com/v1beta/models` prints 200; then `printf %s "$K" \| gcloud secrets versions add gemini-api-key --data-file=-` and `gcloud run services update throughline --region us-central1 --update-env-vars KEY_VERSION=$(date +%s)`. Check with `/api/health?deep=1` → `"gemini":"ok"`. |
| `"online":false` locally | `GEMINI_API_KEY` isn't loaded: run `set -a; source ../.env; set +a` in the backend terminal, then restart uvicorn. |
| Course stuck on "Mapping…" for more than 3 minutes | Locally: check the backend terminal for errors. Live: Cloud Tasks → queue `course-builds`, and the logs (below). |
| A page shows "Something went wrong (reference abc123)" | Logs Explorer → `jsonPayload.request_id="abc123"` |
| The deploy job failed | Open the failed step in Actions. "Smoke test" failed → traffic already went back to the previous version; read the service logs. |
| The live site is broken right now | Roll back: `gcloud run revisions list --service throughline --region us-central1`, then `gcloud run services update-traffic throughline --region us-central1 --to-revisions REVISION=100` |
| Google sign-in popup fails | Check the authorized domain (step 3.3). As a fallback, delete the two `FIREBASE_*` GitHub variables and redeploy: the app switches to anonymous ids. |
| Firestore emulator test won't start | It needs Java 11+: `java -version`. |
| `bootstrap.sh` fails on a permission | You need Owner on `sf-hacks-tutor`. Re-run after fixing; it skips what already exists. |

**Logs:** Google Cloud console → Logging → Logs Explorer, filter `resource.labels.service_name="throughline"`.
**Errors grouped:** console → Error Reporting.

---

## 7. Demo day

**The 5-minute script**

1. **Story (30 s).** "I'm in DS 612. Its prerequisite covers regression. I came in another way and had never seen regression. Quiz 1 covered it."
2. **How it works (45 s).** Open **How it works** (top right). Scroll the pipeline, then use the live knowledge-space demo: mark one concept wrong and watch its foundations and dependents move.
3. **Live map (60 s).** Add the course: number plus syllabus. Show the Bulletin lookup, the timeline and the **prerequisite map**: strings run from what you need first to what builds on it. Open a concept: the quoted line that shows whether a prerequisite taught it.
4. **Student (90 s).** Setup ("equivalent course", 3 h a week) → **quick check**: miss regression, and the next question goes to its foundation, with the reason shown. The plan: foundations first, **Learn** sized in hours, the at-risk warning with the shortfall in minutes.
5. **Why trust it (30 s).** Review map → *How this map was built*: stages, model calls, agreement between the three runs, rejected quotes.
6. **Class (30 s).** Share → QR; judges join on their phones; cells stay hidden until 5 people answer.
7. **SFSU path (15 s).** One-course pilot, TASC drop-ins, an LTI tool reviewed by Academic Technology. No student credentials, ever.

**Live scenario with real files (a transfer student)**

Keep the files on your laptop; never commit them (`private/` is git-ignored).

1. Add **CSC 665** with its syllabus (about 75 seconds to map with Gemini).
2. Setup: **I took an equivalent course somewhere else**, then **Save and see my plan**.
3. **My notes** → it opens on *Another course*; type **CSE 206** and upload the CSE 206 week 2 and week 3 slides
   (and the course curriculum PDF). Each file lists the concepts it covers, with the page.
4. **My plan**: rows matched to the slides now say *Your CSE 206 PDF: … · page N* before the textbook link.
   The point to make: a course from another university counts for this student, page by page, without touching
   the course map other students see.

**Prepare**

- Build the demo course an hour ahead (a Gemini map varies a little between builds), open **Review map** and remove anything weak.
- Don't push to `main` in the last hour before presenting.
- Adding a course needs Google sign-in in production; judges joining by QR need no account.

**Backup:** **Try the sample course** (DEMO 410 with a fictional DEMO 212 prerequisite) works with no network and no Gemini, with a simulated class that is labeled as simulated.
