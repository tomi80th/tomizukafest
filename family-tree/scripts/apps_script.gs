/**
 * Google Apps Script backend for survey.html.  (v3 — minimal Drive scope)
 *
 * Uses the Drive Advanced Service (v3) instead of DriveApp so the script
 * runs under the narrow "drive.file" scope: it can ONLY touch files it
 * created itself, never your existing Drive content.
 *
 * REQUIRED manifest (appsscript.json — Project Settings → show manifest):
 * {
 *   "timeZone": "America/Los_Angeles",
 *   "exceptionLogging": "STACKDRIVER",
 *   "runtimeVersion": "V8",
 *   "dependencies": {
 *     "enabledAdvancedServices": [
 *       { "userSymbol": "Drive", "version": "v3", "serviceId": "drive" }
 *     ]
 *   },
 *   "oauthScopes": [
 *     "https://www.googleapis.com/auth/spreadsheets.currentonly",
 *     "https://www.googleapis.com/auth/drive.file"
 *   ]
 * }
 *
 * After pasting code + manifest: Run testDrive once (authorize), then
 * Deploy → Manage deployments → edit → New version.
 */

const SHEET_NAME = 'responses';
// 'homepage' is appended at the END so pre-existing rows stay aligned.
const FIELDS = ['name', 'email', 'advisor', 'status', 'grad_year',
  'is_professor', 'affiliation', 'title', 'note', 'bio', 'photo_url',
  'source', 'homepage'];

function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  const p = e.parameter || {};

  if (p.photo_data && p.photo_data.indexOf('base64,') > -1) {
    try {
      p.photo_url = savePhoto_(p);
    } catch (err) {
      // keep whatever photo_url the form carried
    }
  }

  sheet.appendRow([new Date()].concat(FIELDS.map(function (f) { return p[f] || ''; })));
  return ContentService.createTextOutput('ok');
}

function savePhoto_(p) {
  const bytes = Utilities.base64Decode(p.photo_data.split('base64,')[1]);
  const safe = (p.name || 'photo').replace(/[^\w\- ]/g, '').trim() || 'photo';
  const name = safe + '.jpg';
  const folderId = getFolderId_();
  // repeat submissions replace the previous upload instead of piling up
  try {
    const prev = Drive.Files.list({
      q: "'" + folderId + "' in parents and name = '" +
         name.replace(/'/g, "\\'") + "' and trashed = false",
      fields: 'files(id)',
    });
    (prev.files || []).forEach(function (f) {
      Drive.Files.update({ trashed: true }, f.id);
    });
  } catch (err) { /* cleanup is best-effort */ }
  const blob = Utilities.newBlob(bytes, 'image/jpeg', name);
  const file = Drive.Files.create({ name: name, parents: [folderId] }, blob);
  Drive.Permissions.create({ type: 'anyone', role: 'reader' }, file.id);
  return 'https://drive.google.com/uc?export=download&id=' + file.id;
}

// The folder id is cached in script properties, so we never need to SEARCH
// Drive (searching is what requires the broad scope).
function getFolderId_() {
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty('photoFolderId');
  if (!id) {
    const folder = Drive.Files.create({
      name: 'TomiTreePhotos',
      mimeType: 'application/vnd.google-apps.folder',
    });
    id = folder.id;
    props.setProperty('photoFolderId', id);
  }
  return id;
}

// Run this once in the editor to authorize and create the photo folder.
function testDrive() {
  Logger.log('TomiTreePhotos folder id: ' + getFolderId_());
}

// GET returns the responses as CSV (email column excluded) for the site build.
// ?ping=1 returns the code version instead, to verify what the deployment runs.
function doGet(e) {
  if (e && e.parameter && e.parameter.ping) {
    return ContentService.createTextOutput('v3-drivefile');
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  const values = sheet.getDataRange().getValues();
  const header = ['timestamp'].concat(FIELDS);
  const emailIdx = header.indexOf('email');
  const rows = values.map(function (r, i) {
    // pad old rows that predate newly appended columns
    const row = i === 0 ? header : header.map(function (_, j) {
      return j < r.length ? r[j] : '';
    });
    return row.filter(function (_, j) { return j !== emailIdx; })
      .map(function (c) {
        const s = String(c).replace(/"/g, '""');
        return /[",\n]/.test(s) ? '"' + s + '"' : s;
      }).join(',');
  });
  return ContentService.createTextOutput(rows.join('\n'))
    .setMimeType(ContentService.MimeType.CSV);
}
