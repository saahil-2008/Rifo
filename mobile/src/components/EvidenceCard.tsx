import React from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { STANCE_META } from '../theme';
import type { EvidenceItem } from '../types';

function formatDate(iso: string | null): string {
  if (!iso) {
    return '';
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** One source card: domain, stance, date, snippet, outbound link (FR-9 #3). */
export default function EvidenceCard({ item }: { item: EvidenceItem }): React.JSX.Element {
  const stance = STANCE_META[item.stance] ?? STANCE_META.neutral;
  const date = formatDate(item.published_at);
  const canOpen = item.url.startsWith('http://') || item.url.startsWith('https://');

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.domain} numberOfLines={1}>
          {item.domain || 'unknown source'}
        </Text>
        <View style={[styles.stance, { borderColor: stance.color }]}>
          <Text style={[styles.stanceText, { color: stance.color }]}>{stance.title}</Text>
        </View>
      </View>

      {item.title ? <Text style={styles.title} numberOfLines={2}>{item.title}</Text> : null}

      {item.snippet ? <Text style={styles.snippet} numberOfLines={3}>{item.snippet}</Text> : null}

      <View style={styles.footer}>
        {date ? <Text style={styles.date}>{date}</Text> : <Text style={styles.date}>date unknown</Text>}
        <Text style={styles.cred}>credibility {(item.credibility * 100).toFixed(0)}%</Text>
        {canOpen ? (
          <Pressable onPress={() => Linking.openURL(item.url).catch(() => undefined)}>
            <Text style={styles.link}>Open ↗</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0E0E0',
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  domain: { flex: 1, fontSize: 13, fontWeight: '700', color: '#1A1A1A', marginRight: 8 },
  stance: { borderRadius: 999, borderWidth: 1, paddingHorizontal: 8, paddingVertical: 2 },
  stanceText: { fontSize: 11, fontWeight: '700' },
  title: { marginTop: 6, fontSize: 14, fontWeight: '600', color: '#212121' },
  snippet: { marginTop: 4, fontSize: 12, lineHeight: 17, color: '#424242' },
  footer: { marginTop: 8, flexDirection: 'row', alignItems: 'center' },
  date: { fontSize: 11, color: '#757575', flex: 1 },
  cred: { fontSize: 11, color: '#757575', marginRight: 10 },
  link: { fontSize: 12, fontWeight: '700', color: '#1565C0' },
});
