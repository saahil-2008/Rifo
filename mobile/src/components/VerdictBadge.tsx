import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { VERDICT_META, formatConfidence } from '../theme';
import type { VerdictLabel } from '../types';

interface Props {
  label: VerdictLabel;
  confidence?: number;
  size?: 'small' | 'large';
}

/** Coloured verdict chip with confidence — used on cards and the Detail header. */
export default function VerdictBadge({ label, confidence, size = 'small' }: Props): React.JSX.Element {
  const meta = VERDICT_META[label] ?? VERDICT_META.insufficient;
  const isLarge = size === 'large';
  return (
    <View
      style={[
        styles.badge,
        { backgroundColor: meta.accent },
        isLarge && styles.badgeLarge,
      ]}>
      <Text style={[styles.label, isLarge && styles.labelLarge]}>{meta.title}</Text>
      {confidence !== undefined && (
        <Text style={styles.confidence}>{formatConfidence(confidence)}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  badgeLarge: {
    paddingHorizontal: 16,
    paddingVertical: 6,
  },
  label: { color: '#FFFFFF', fontSize: 12, fontWeight: '700', letterSpacing: 0.2 },
  labelLarge: { fontSize: 18 },
  confidence: { color: '#FFFFFF', fontSize: 11, marginLeft: 6, opacity: 0.9 },
});
