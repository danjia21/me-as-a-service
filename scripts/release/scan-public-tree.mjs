#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { lstatSync, readFileSync, readlinkSync, readdirSync } from "node:fs";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  posix,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath } from "node:url";

const FORBIDDEN_PATHS = [
  /^private(?:\/|$)/,
  /^AGENTS\.md$/,
  /(?:^|\/)\.env$/,
  /(?:^|\/).*\.tfstate(?:\.|$)/,
  /(?:^|\/).*\.tfplan$/,
  /(?:^|\/)\.terraform(?:\/|$)/,
];

const SECRET_PATTERNS = [
  {
    name: "private key",
    pattern: /-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----/,
  },
  { name: "AWS access key", pattern: /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/ },
  { name: "GitHub token", pattern: /\bgh[pousr]_[A-Za-z0-9]{30,}\b/ },
  { name: "OpenAI-style key", pattern: /\bsk-[A-Za-z0-9_-]{32,}\b/ },
  { name: "Slack token", pattern: /\bxox[baprs]-[A-Za-z0-9-]{20,}\b/ },
];
const ASSIGNED_SECRET_PATTERN =
  /(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|SECRET_ACCESS_KEY|PASSWORD)[ \t]*[:=][ \t]*["']?([A-Za-z0-9+/=_-]{16,})/g;
const PLACEHOLDER_PATTERN = /(?:example|placeholder|replace-me|your[-_])/i;

function walkFiles(root, directory = root) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === ".git") {
      continue;
    }
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkFiles(root, absolute));
    } else if (entry.isFile()) {
      files.push(relative(root, absolute).split(sep).join("/"));
    }
  }
  return files;
}

function trackedFiles(root) {
  try {
    const output = execFileSync(
      "git",
      ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
      {
        cwd: root,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      },
    );
    return output.split("\0").filter(Boolean).sort();
  } catch {
    return walkFiles(root).sort();
  }
}

function scanEntry(path, buffer, identifiers, findings, displayPath = path) {
  for (const forbidden of FORBIDDEN_PATHS) {
    if (forbidden.test(path)) {
      findings.push({ path: displayPath, kind: "forbidden path" });
    }
  }

  const content = buffer.toString("utf8");

  for (const { name, pattern } of SECRET_PATTERNS) {
    if (pattern.test(content)) {
      findings.push({ path: displayPath, kind: name });
    }
  }
  for (const match of content.matchAll(ASSIGNED_SECRET_PATTERN)) {
    if (!PLACEHOLDER_PATTERN.test(match[1])) {
      findings.push({ path: displayPath, kind: "assigned secret" });
      break;
    }
  }

  for (const identifierEntry of identifiers) {
    const identifier =
      typeof identifierEntry === "string"
        ? identifierEntry
        : identifierEntry.value;
    const allowedPaths =
      typeof identifierEntry === "string" ? [] : identifierEntry.allowed_paths;
    if (
      identifier &&
      !allowedPaths.includes(path) &&
      (path.toLocaleLowerCase().includes(identifier.toLocaleLowerCase()) ||
        content.toLocaleLowerCase().includes(identifier.toLocaleLowerCase()))
    ) {
      findings.push({ path: displayPath, kind: "private identifier" });
    }
  }
}

export function scanPublicTree({
  root,
  files = trackedFiles(root),
  identifiers = [],
}) {
  const findings = [];
  const normalizedFiles = [...files].sort();

  for (const path of normalizedFiles) {
    const absolute = resolve(root, path);
    if (!absolute.startsWith(`${resolve(root)}${sep}`)) {
      findings.push({ path, kind: "invalid file entry" });
      continue;
    }
    let entry;
    try {
      entry = lstatSync(absolute);
    } catch {
      findings.push({ path, kind: "invalid file entry" });
      continue;
    }
    if (entry.isSymbolicLink()) {
      const target = readlinkSync(absolute);
      const resolvedTarget = resolve(dirname(absolute), target);
      if (
        isAbsolute(target) ||
        !resolvedTarget.startsWith(`${resolve(root)}${sep}`)
      ) {
        findings.push({ path, kind: "unsafe symbolic link" });
        continue;
      }
      scanEntry(path, Buffer.from(target), identifiers, findings);
    } else if (entry.isFile()) {
      scanEntry(path, readFileSync(absolute), identifiers, findings);
    } else {
      findings.push({ path, kind: "invalid file entry" });
    }
  }

  return findings;
}

export function scanPublicHistory({ root, identifiers = [] }) {
  const findings = [];
  const commits = execFileSync("git", ["rev-list", "--all"], {
    cwd: root,
    encoding: "utf8",
  })
    .split(/\r?\n/)
    .filter(Boolean);
  const seen = new Set();

  for (const commit of commits) {
    const entries = execFileSync("git", ["ls-tree", "-r", "-z", commit], {
      cwd: root,
    })
      .toString("utf8")
      .split("\0")
      .filter(Boolean);

    for (const entry of entries) {
      const tab = entry.indexOf("\t");
      const [mode, type, object] = entry.slice(0, tab).split(" ");
      const path = entry.slice(tab + 1);
      if (type !== "blob" || !["100644", "100755", "120000"].includes(mode)) {
        findings.push({
          path: `${commit.slice(0, 12)}:${path}`,
          kind: "unsupported Git object",
        });
        continue;
      }
      const identity = `${object}\0${path}`;
      if (seen.has(identity)) {
        continue;
      }
      seen.add(identity);
      const content = execFileSync("git", ["cat-file", "blob", object], {
        cwd: root,
        encoding: "buffer",
        maxBuffer: 1024 * 1024 * 256,
      });
      if (mode === "120000") {
        const target = content.toString("utf8");
        const resolvedTarget = posix.normalize(
          posix.join(posix.dirname(path), target),
        );
        if (
          posix.isAbsolute(target) ||
          resolvedTarget === ".." ||
          resolvedTarget.startsWith("../")
        ) {
          findings.push({
            path: `${commit.slice(0, 12)}:${path}`,
            kind: "unsafe symbolic link",
          });
          continue;
        }
      }
      scanEntry(
        path,
        content,
        identifiers,
        findings,
        `${commit.slice(0, 12)}:${path}`,
      );
    }
  }
  return findings;
}

function readIdentifiers(path) {
  if (!path) {
    return [];
  }
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => {
      const [value, ...allowedPaths] = line
        .split("|")
        .map((part) => part.trim());
      return { value, allowed_paths: allowedPaths.filter(Boolean) };
    });
}

function parseArguments(arguments_) {
  let root = ".";
  let identifiersPath;
  let history = false;

  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === "--identifiers") {
      identifiersPath = arguments_[index + 1];
      index += 1;
    } else if (argument === "--history") {
      history = true;
    } else if (argument === "--help") {
      console.log(
        "Usage: scan-public-tree.mjs [ROOT] [--history] [--identifiers PRIVATE_FILE]",
      );
      process.exit(0);
    } else if (argument.startsWith("-")) {
      throw new Error(`unknown argument: ${argument}`);
    } else {
      root = argument;
    }
  }
  return { root: resolve(root), identifiersPath, history };
}

const isMain =
  process.argv[1] &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));

if (isMain) {
  try {
    const { root, identifiersPath, history } = parseArguments(
      process.argv.slice(2),
    );
    const identifiers = readIdentifiers(identifiersPath);
    const findings = history
      ? scanPublicHistory({ root, identifiers })
      : scanPublicTree({ root, identifiers });

    if (findings.length > 0) {
      console.error(`Public tree scan failed (${findings.length} finding(s)):`);
      for (const finding of findings) {
        console.error(`- ${finding.path}: ${finding.kind}`);
      }
      process.exit(1);
    }

    console.log(`Public tree scan passed: ${basename(root)}`);
  } catch (error) {
    console.error(`Public tree scan failed: ${error.message}`);
    process.exit(2);
  }
}
