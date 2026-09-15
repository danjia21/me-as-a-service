import "server-only";

import fs from "node:fs";
import path from "node:path";
import { parse } from "yaml";

export type InstanceConfig = {
  display_name: string;
  representation_label: string;
  disclosure: string;
  welcome_message: string;
  suggested_questions: string[];
  links: {
    public_profile?: string;
    repository?: string;
  };
};

export type PublicInstanceConfig = Pick<
  InstanceConfig,
  | "display_name"
  | "representation_label"
  | "disclosure"
  | "welcome_message"
  | "suggested_questions"
  | "links"
>;

export function loadPublicInstance(): PublicInstanceConfig {
  const instance = loadInstance();
  return {
    display_name: instance.display_name,
    representation_label: instance.representation_label,
    disclosure: instance.disclosure,
    welcome_message: instance.welcome_message,
    suggested_questions: selectSuggestedQuestions(instance.suggested_questions),
    links: instance.links,
  };
}

function selectSuggestedQuestions(questions: string[]): string[] {
  if (questions.length <= 3) {
    return questions;
  }

  const shuffled = [...questions];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[randomIndex]] = [
      shuffled[randomIndex],
      shuffled[index],
    ];
  }
  return shuffled.slice(0, 3);
}

export function loadInstance(): InstanceConfig {
  const repositoryRoot = findRepositoryRoot(process.cwd());
  const configuredDirectory =
    process.env.MAAS_INSTANCE_DIR ?? "instance/example";
  const instanceDirectory = path.isAbsolute(configuredDirectory)
    ? configuredDirectory
    : path.join(repositoryRoot, configuredDirectory);
  const manifestPath = path.join(instanceDirectory, "instance.yaml");
  const config = parse(fs.readFileSync(manifestPath, "utf8")) as unknown;

  assertInstanceConfig(config);
  return config;
}

function assertInstanceConfig(value: unknown): asserts value is InstanceConfig {
  if (!value || typeof value !== "object") {
    throw new Error("instance.yaml must contain an object");
  }
  const config = value as Partial<InstanceConfig>;
  if (
    typeof config.display_name !== "string" ||
    typeof config.representation_label !== "string" ||
    typeof config.disclosure !== "string" ||
    typeof config.welcome_message !== "string" ||
    !Array.isArray(config.suggested_questions) ||
    !config.suggested_questions.every(
      (question) => typeof question === "string" && question.length > 0,
    ) ||
    !config.links
  ) {
    throw new Error("instance.yaml is missing required presentation fields");
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
