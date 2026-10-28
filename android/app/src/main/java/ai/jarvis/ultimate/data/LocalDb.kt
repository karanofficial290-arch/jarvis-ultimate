package ai.jarvis.ultimate.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/** Notes and reminders created on the phone are stored locally (Room), not in the cloud. */
@Entity(tableName = "notes")
data class NoteEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val title: String,
    val content: String,
    val kind: String = "note",           // "note" | "reminder"
    val createdAt: Long = System.currentTimeMillis(),
)

/** Phone-only mode: saved memories live on the phone. */
@Entity(tableName = "memories")
data class MemoryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val kind: String,
    val content: String,
    val source: String = "user",
    val updatedAt: Long = System.currentTimeMillis(),
)

/** Phone-only mode: automation history. */
@Entity(tableName = "audit")
data class AuditEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val actor: String,
    val event: String,
    val tool: String?,
    val status: String,
    val createdAt: Long = System.currentTimeMillis(),
)

@Dao
interface NoteDao {
    @Insert suspend fun insert(note: NoteEntity): Long
    @Query("SELECT * FROM notes ORDER BY createdAt DESC") fun all(): Flow<List<NoteEntity>>
    @Query("DELETE FROM notes WHERE id = :id") suspend fun delete(id: Long): Int
}

@Dao
interface MemoryDao {
    @Insert suspend fun insert(m: MemoryEntity): Long
    @Query("SELECT * FROM memories WHERE id = :id") suspend fun get(id: Long): MemoryEntity?
    @Query("SELECT * FROM memories ORDER BY updatedAt DESC LIMIT 200") suspend fun all(): List<MemoryEntity>
    @Query("SELECT * FROM memories WHERE content LIKE '%' || :q || '%' ORDER BY updatedAt DESC LIMIT 50") suspend fun search(q: String): List<MemoryEntity>
    @Query("SELECT * FROM memories WHERE kind = 'preference' ORDER BY updatedAt DESC LIMIT 5") suspend fun preferences(): List<MemoryEntity>
    @Query("DELETE FROM memories WHERE id = :id") suspend fun delete(id: Long): Int
    @Query("DELETE FROM memories") suspend fun clear(): Int
}

@Dao
interface AuditDao {
    @Insert suspend fun insert(a: AuditEntity): Long
    @Query("SELECT * FROM audit ORDER BY id DESC LIMIT 200") suspend fun recent(): List<AuditEntity>
}

@Database(entities = [NoteEntity::class, MemoryEntity::class, AuditEntity::class], version = 2, exportSchema = false)
abstract class LocalDb : RoomDatabase() {
    abstract fun notes(): NoteDao
    abstract fun memories(): MemoryDao
    abstract fun audit(): AuditDao

    companion object {
        fun create(context: Context): LocalDb =
            Room.databaseBuilder(context, LocalDb::class.java, "jarvis_local.db")
                .fallbackToDestructiveMigration()   // v0.1 had no released local data to preserve
                .build()
    }
}
