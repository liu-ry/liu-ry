import { readFileSync, writeFileSync } from "node:fs";

const file = new URL("../assets/github-stars-total.svg", import.meta.url);
let svg = readFileSync(file, "utf8");

const staticLinePattern =
  /<path fill="none" stroke="#dd4528" d="([^"]+)" class="xkcd-chart-xyline" filter="url\(#xkcdify\)"\/>/;
const animatedLinePattern =
  /<path id="star-race-track" fill="none" stroke="#dd4528" d="([^"]+)" class="xkcd-chart-xyline" filter="url\(#xkcdify\)" pathLength="1000" stroke-dasharray="1000" stroke-dashoffset="0">[\s\S]*?<\/path>/;
const lineMatch = svg.match(staticLinePattern) || svg.match(animatedLinePattern);

if (!lineMatch) {
  throw new Error("Could not find the red star-history line to animate.");
}

const trackPath = lineMatch[1];
const animatedLine = `<path id="star-race-track" fill="none" stroke="#dd4528" d="${trackPath}" class="xkcd-chart-xyline" filter="url(#xkcdify)" pathLength="1000" stroke-dasharray="1000" stroke-dashoffset="0">
      <animate attributeName="stroke-dashoffset" values="1000;0;0" keyTimes="0;.82;1" dur="6s" repeatCount="indefinite"/>
    </path>`;

const raceCar = `    <g id="star-race-car" transform="translate(-14 -11)">
      <animateMotion dur="6s" repeatCount="indefinite" rotate="auto" keyPoints="0;1;1" keyTimes="0;.82;1" calcMode="linear">
        <mpath href="#star-race-track"/>
      </animateMotion>
      <path d="M-18 8c-7 0-12 3-15 8" fill="none" stroke="#f6b73c" stroke-linecap="round" stroke-width="3" opacity=".75">
        <animate attributeName="opacity" values=".1;.75;.1" dur=".28s" repeatCount="indefinite"/>
      </path>
      <path d="M5 4h19l8 9h6c4 0 7 3 7 7v4H-3v-9c0-6 3-11 8-11Z" fill="#ef4438" stroke="#111" stroke-linejoin="round" stroke-width="2.5"/>
      <path d="M21 6l6 7H13l3-7Z" fill="#9fe7ff" stroke="#111" stroke-linejoin="round" stroke-width="2"/>
      <path d="M-2 17h47" stroke="#fff7d6" stroke-linecap="round" stroke-width="2"/>
      <circle cx="8" cy="26" r="6" fill="#111"/>
      <circle cx="34" cy="26" r="6" fill="#111"/>
      <circle cx="8" cy="26" r="2.4" fill="#fff"/>
      <circle cx="34" cy="26" r="2.4" fill="#fff"/>
    </g>`;

if (!svg.includes('id="star-race-track"')) {
  svg = svg.replace(staticLinePattern, animatedLine);
}

svg = svg.replace(/    <g id="star-race-car"[\s\S]*?^    <\/g>\n?/m, "");

const legendPattern = /(\n    <svg>\n      <svg><rect width="171\.5")/;
if (!legendPattern.test(svg)) {
  throw new Error("Could not find the chart legend insertion point for the race car.");
}
svg = svg.replace(legendPattern, `\n${raceCar}$1`);

writeFileSync(file, svg);
console.log("Injected star race animation.");
