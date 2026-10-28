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

@Dao
interface NoteDao {
    @Insert suspend fun insert(note: NoteEntity): Long
    @Query("SELECT * FROM notes ORDER BY createdAt DESC") fun all(): Flow<List<NoteEntity>>
    @Query("DELETE FROM notes WHERE id = :id") suspend fun delete(id: Long): Int
}

@Database(entities = [NoteEntity::class], version = 1, exportSchema = false)
abstract class LocalDb : RoomDatabase() {
    abstract fun notes(): NoteDao

    companion object {
        fun create(context: Context): LocalDb =
            Room.databaseBuilder(context, LocalDb::class.java, "jarvis_local.db").build()
    }
}
