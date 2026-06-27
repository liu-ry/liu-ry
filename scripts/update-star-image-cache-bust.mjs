import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";

const svgFile = new URL("../assets/github-stars-total.svg", import.meta.url);
const readmeFile = new URL("../README.md", import.meta.url);

const svg = readFileSync(svgFile);
const version = createHash("sha256").update(svg).digest("hex").slice(0, 12);
let readme = readFileSync(readmeFile, "utf8");

const imagePattern = /src="\.\/assets\/github-stars-total\.svg(?:\?v=[a-f0-9]+)?"/;
if (!imagePattern.test(readme)) {
  throw new Error("Could not find the star history image in README.md.");
}

readme = readme.replace(imagePattern, `src="./assets/github-stars-total.svg?v=${version}"`);
writeFileSync(readmeFile, readme);
console.log(`Updated star history image cache buster to ${version}.`);
