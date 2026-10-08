# Hugging Face Job spike

A one-off check of whether a Hugging Face Job can run the weekly pipeline. It
answers four questions before anything is built on it:

1. Does the job container run as root, so `apt-get` can install Tesseract?
2. Do Tesseract and the French language data work there?
3. Does this repository's test suite pass in the job's environment?
4. Can the job reach montolieu.fr?

It also tests (optionally) whether a job can write to a mounted Storage Bucket,
which is where mutable private state would live.

## What it does not do

It does not OCR real PDFs, time a full run, schedule anything, or decide how
private state is stored. It downloads no PDFs: the sync step is a dry run, so
the Mairie's server sees only two requests.

## Run it

You need the `hf` command and a Hugging Face account with a positive credit
balance (Jobs are pay-as-you-go; see
https://huggingface.co/docs/huggingface_hub/en/guides/jobs).

```bash
hf auth login
```

```bash
hf jobs run --flavor cpu-basic --timeout 20m --name echo-spike python:3.12 bash -c "$(cat jobs/spike.sh)"
```

To test a branch that is not merged yet, add `-e REPO_REF=BRANCH_NAME` before
the image name. The command streams the log and exits non-zero if the job fails. At the
documented `cpu-basic` price of $0.01 per hour, a run capped at 20 minutes costs
at most about a third of a cent.

To also test writing to a Storage Bucket, create one (see
https://huggingface.co/docs/hub/storage-buckets) and add this option, replacing
the bucket name:

```bash
-v hf://buckets/YOUR_USER/YOUR_BUCKET:/mnt/spike
```

## Reading the result

| Log section | Good result | Means if it fails |
|---|---|---|
| `who am I` | `uid=0(root)` | No root: use a prebuilt image that already contains Tesseract. |
| package install | no errors | The container cannot install packages. |
| `tesseract --list-langs` | lists `fra` | French data missing. |
| test suite | `119 passed` or similar | Environment differs from the one tested here. |
| dry-run sync | JSON with `would_fetch` and exit 0 | The job cannot reach montolieu.fr, or it was refused. |
| bucket write | prints a UTC date | The bucket is not mounted or not writable. |

## Things to decide from the result

- The Debian `tesseract-ocr-fra` package is the *fast* French model. The tests
  and OCR checks in this project used `tessdata_best`, which is more accurate
  and slower. The real job should download that file, so the output matches.
- Mutable private state (the index, kept versions and archived PDFs) belongs in
  a Storage Bucket. Dataset and model repositories mount read-only in a Job;
  only buckets are read-write.
