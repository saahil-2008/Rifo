import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useCallback, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { VERDICT_META, formatCheckCount } from '../theme';
import { loadHistory } from '../historyStore';
import VerdictBadge from '../components/VerdictBadge';
import type { RootStackParamList } from '../navigation';
import type { HistoryRow } from '../types';

type Props = NativeStackScreenProps<RootStackParamList, 'History'>;

function timeAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function HistoryScreen({ navigation }: Props): React.JSX.Element {
  const [rows, setRows] = useState<HistoryRow[]>([]);

  const refresh = useCallback(async () => {
    setRows(await loadHistory());
  }, []);

  React.useEffect(() => {
    const unsub = navigation.addListener('focus', () => {
      void refresh();
    });
    void refresh();
    return unsub;
  }, [navigation, refresh]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>History</Text>
        <Pressable onPress={() => navigation.navigate('Settings')} hitSlop={8}>
          <Text style={styles.gear}>⚙</Text>
        </Pressable>
      </View>

      {rows.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Nothing checked yet</Text>
          <Text style={styles.emptyBody}>
            Open any app, long-press the Rifo bubble, and results will appear here.
          </Text>
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: 12 }}
          renderItem={({ item }) => (
            <Pressable
              style={styles.card}
              onPress={() => navigation.navigate('Detail', { claimId: item.claimId })}>
              <View style={styles.cardRow}>
                <VerdictBadge label={item.label} confidence={item.confidence} />
                <Text style={styles.when}>{timeAgo(item.createdAt)}</Text>
              </View>
              <Text style={styles.claim} numberOfLines={2}>
                {item.claimOriginal && item.claimOriginal !== item.claim
                  ? item.claimOriginal
                  : item.claim}
              </Text>
              <Text style={styles.meta}>
                {item.checkCount > 0
                  ? `Checked ${formatCheckCount(item.checkCount)} times`
                  : 'New check'}
              </Text>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#FAFAFA' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 6,
  },
  title: { fontSize: 28, fontWeight: '800', color: '#0A2E5C' },
  gear: { fontSize: 22, color: '#546E7A' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 },
  emptyTitle: { fontSize: 17, fontWeight: '700', color: '#37474F' },
  emptyBody: {
    fontSize: 14,
    color: '#607D8B',
    textAlign: 'center',
    marginTop: 8,
    lineHeight: 20,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0E0E0',
  },
  cardRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  when: { fontSize: 12, color: '#90A4AE' },
  claim: { fontSize: 15, fontWeight: '600', color: '#212121', marginTop: 8 },
  meta: { fontSize: 12, color: '#78909C', marginTop: 6 },
});
