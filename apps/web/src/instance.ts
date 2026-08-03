import "server-only";

import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

export type InstanceConfig = {
  schema_version: 1;
  id: string;
  display_name: string;
  representation_label: string;
  disclosure: string;
  knowledge: { path: string };
  evaluations?: { questions: string };
  suggested_questions: string[];
  links: {
    public_profile?: string;
    repository?: string;
  };
  routing: {
    personal_terms: string[];
  };
};

export type PublicInstanceConfig = Pick<
  InstanceConfig,
  "display_name" | "representation_label" | "suggested_questions" | "links"
>;

export function loadPublicInstance(): PublicInstanceConfig {
  const instance = loadInstance();
  return {
    display_name: instance.display_name,
    representation_label: instance.representation_label,
    suggested_questions: instance.suggested_questions,
    links: instance.links,
  };
}

export function loadInstance(): InstanceConfig {
  const repositoryRoot = findRepositoryRoot(process.cwd());
  const configuredDirectory =
    process.env.MAAS_INSTANCE_DIR ?? "examples/fictional-profile";
  const instanceDirectory = path.isAbsolute(configuredDirectory)
    ? configuredDirectory
    : path.join(repositoryRoot, configuredDirectory);
  const manifestPath = path.join(instanceDirectory, "instance.yaml");
  const config = parse(fs.readFileSync(manifestPath, "utf8")) as unknown;

  assertInstanceConfig(config);
  assertRelativeInstancePath(config.knowledge.path);
  if (config.evaluations) {
    assertRelativeInstancePath(config.evaluations.questions);
  }
  return config;
}

function assertInstanceConfig(value: unknown): asserts value is InstanceConfig {
  if (!value || typeof value !== "object") {
    throw new Error("instance.yaml must contain an object");
  }
  const config = value as Partial<InstanceConfig>;
  if (
    config.schema_version !== 1 ||
    typeof config.id !== "string" ||
    !/^[a-z0-9][a-z0-9-]*$/.test(config.id) ||
    typeof config.display_name !== "string" ||
    typeof config.representation_label !== "string" ||
    typeof config.disclosure !== "string" ||
    !config.knowledge ||
    typeof config.knowledge.path !== "string" ||
    !Array.isArray(config.suggested_questions) ||
    !config.suggested_questions.every(
      (question) => typeof question === "string" && question.length > 0,
    ) ||
    !config.links ||
    !config.routing ||
    !Array.isArray(config.routing.personal_terms) ||
    config.routing.personal_terms.length === 0
  ) {
    throw new Error("instance.yaml does not match schema version 1");
  }
}

function assertRelativeInstancePath(value: string) {
  const normalized = path.posix.normalize(value);
  if (
    !value ||
    path.posix.isAbsolute(value) ||
    normalized === ".." ||
    normalized.startsWith("../")
  ) {
    throw new Error("instance paths must remain inside the instance directory");
  }
}

function findRepositoryRoot(start: string): string {
  let current = path.resolve(start);
  while (true) {
    if (fs.existsSync(path.join(current, "pnpm-workspace.yaml"))) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return start;
    }
    current = parent;
  }
}
