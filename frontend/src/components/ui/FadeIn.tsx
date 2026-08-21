"use client";

import { motion, type HTMLMotionProps } from "framer-motion";

export type FadeInDirection = "up" | "down" | "left" | "right" | "none";

type FadeInProps = HTMLMotionProps<"div"> & {
  delay?: number;
  direction?: FadeInDirection;
  duration?: number;
  /**
   * true にすると「SSR 時点から可視」になる（初期状態を animate 側の値にし、演出をしない）。
   *
   * 背景（2026-08-21 外部レビュー F13）: 既定の FadeIn は SSR HTML に `opacity:0` を焼くため、
   * hydration とアニメーション開始まで中身が見えない。トップの H1・ヒーロー説明文・主要 CTA が
   * これに包まれており、Codex の PageSpeed 実測で mobile LCP 4.4〜4.5 秒（LCP 要素 = ヒーロー
   * 説明文、render delay が LCP の約 79%）だった。ファーストビューだけ immediate にする。
   * ページ下部の FadeIn は従来どおり（スクロールしてから見えるので LCP に効かない）。
   */
  immediate?: boolean;
};

const OFFSET = 24;

const directionMap = {
  up: { y: OFFSET, x: 0 },
  down: { y: -OFFSET, x: 0 },
  left: { x: OFFSET, y: 0 },
  right: { x: -OFFSET, y: 0 },
  none: { x: 0, y: 0 },
} as const;

/**
 * motion.div に渡す initial を決める。immediate なら `false`
 * （framer-motion は initial:false のとき animate の値をそのまま初期スタイルとして
 * SSR/初回 paint に出す＝ opacity:0 が HTML に焼かれない）。
 */
export function fadeInInitial(
  direction: FadeInDirection = "up",
  immediate = false,
): false | { opacity: number; x: number; y: number } {
  if (immediate) return false;
  const offset = directionMap[direction];
  return { opacity: 0, x: offset.x, y: offset.y };
}

export function FadeIn({
  delay = 0,
  direction = "up",
  duration = 0.5,
  immediate = false,
  children,
  ...props
}: FadeInProps) {
  return (
    <motion.div
      initial={fadeInInitial(direction, immediate)}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={
        immediate ? { duration: 0 } : { duration, delay, ease: [0.25, 0.46, 0.45, 0.94] }
      }
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function StaggerContainer({
  children,
  className,
  stagger = 0.08,
}: {
  children: React.ReactNode;
  className?: string;
  stagger?: number;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="visible"
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: stagger } },
      }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 16 },
        visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] } },
      }}
    >
      {children}
    </motion.div>
  );
}
