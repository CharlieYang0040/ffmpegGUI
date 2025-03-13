from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.services.logging_service import LoggingService

class Command(ABC):
    """
    명령 패턴의 기본 추상 클래스
    
    모든 명령은 이 클래스를 상속받아 execute와 undo 메서드를 구현해야 합니다.
    """
    
    def __init__(self, description: str = ""):
        """
        명령 초기화
        
        Args:
            description: 명령에 대한 설명
        """
        self.description = description
        self.logger = LoggingService().get_logger(__name__)
    
    @abstractmethod
    def execute(self) -> bool:
        """
        명령을 실행합니다.
        
        Returns:
            bool: 명령 실행 성공 여부
        """
        pass
    
    @abstractmethod
    def undo(self) -> bool:
        """
        명령을 취소합니다.
        
        Returns:
            bool: 명령 취소 성공 여부
        """
        pass
    
    def __str__(self) -> str:
        return self.description


class CommandManager:
    """
    명령 관리자 클래스
    
    명령의 실행, 취소, 다시 실행을 관리합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CommandManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        self.history: List[Command] = []
        self.redos: List[Command] = []
        self.max_history = 50
        self.logger = LoggingService().get_logger(__name__)
        self.logger.debug("CommandManager 초기화됨")
    
    def execute(self, command: Command) -> bool:
        """
        명령을 실행하고 히스토리에 추가합니다.
        
        Args:
            command: 실행할 명령
            
        Returns:
            bool: 명령 실행 성공 여부
        """
        result = command.execute()
        if result:
            self.history.append(command)
            self.redos.clear()
            
            # 히스토리 크기 제한
            if len(self.history) > self.max_history:
                self.history.pop(0)
                
            self.logger.debug(f"명령 실행: {command}")
        else:
            self.logger.warning(f"명령 실행 실패: {command}")
        
        return result
    
    def undo(self) -> bool:
        """
        가장 최근 명령을 취소합니다.
        
        Returns:
            bool: 명령 취소 성공 여부
        """
        if not self.history:
            self.logger.debug("취소할 명령 없음")
            return False
        
        command = self.history.pop()
        result = command.undo()
        
        if result:
            self.redos.append(command)
            self.logger.debug(f"명령 취소: {command}")
        else:
            self.logger.warning(f"명령 취소 실패: {command}")
            # 취소 실패 시 히스토리에 다시 추가
            self.history.append(command)
        
        return result
    
    def redo(self) -> bool:
        """
        가장 최근에 취소된 명령을 다시 실행합니다.
        
        Returns:
            bool: 명령 다시 실행 성공 여부
        """
        if not self.redos:
            self.logger.debug("다시 실행할 명령 없음")
            return False
        
        command = self.redos.pop()
        result = command.execute()
        
        if result:
            self.history.append(command)
            self.logger.debug(f"명령 다시 실행: {command}")
        else:
            self.logger.warning(f"명령 다시 실행 실패: {command}")
            # 다시 실행 실패 시 redo 목록에 다시 추가
            self.redos.append(command)
        
        return result
    
    def can_undo(self) -> bool:
        """
        취소 가능한 명령이 있는지 확인합니다.
        
        Returns:
            bool: 취소 가능 여부
        """
        return len(self.history) > 0
    
    def can_redo(self) -> bool:
        """
        다시 실행 가능한 명령이 있는지 확인합니다.
        
        Returns:
            bool: 다시 실행 가능 여부
        """
        return len(self.redos) > 0
    
    def clear(self) -> None:
        """
        모든 명령 히스토리를 지웁니다.
        """
        self.history.clear()
        self.redos.clear()
        self.logger.debug("명령 히스토리 초기화됨")
    
    def get_undo_description(self) -> Optional[str]:
        """
        다음 취소 명령의 설명을 반환합니다.
        
        Returns:
            Optional[str]: 취소 명령 설명 또는 None
        """
        if self.can_undo():
            return str(self.history[-1])
        return None
    
    def get_redo_description(self) -> Optional[str]:
        """
        다음 다시 실행 명령의 설명을 반환합니다.
        
        Returns:
            Optional[str]: 다시 실행 명령 설명 또는 None
        """
        if self.can_redo():
            return str(self.redos[-1])
        return None


# 명령 구현 예시
class TrimCommand(Command):
    """
    미디어 파일 트리밍 명령
    """
    
    def __init__(self, file_id: str, old_start: int, old_end: int, new_start: int, new_end: int):
        """
        트리밍 명령 초기화
        
        Args:
            file_id: 파일 ID
            old_start: 이전 시작 시간
            old_end: 이전 종료 시간
            new_start: 새 시작 시간
            new_end: 새 종료 시간
        """
        super().__init__(f"트리밍 변경: {file_id} ({old_start}-{old_end} → {new_start}-{new_end})")
        self.file_id = file_id
        self.old_start = old_start
        self.old_end = old_end
        self.new_start = new_start
        self.new_end = new_end
    
    def execute(self) -> bool:
        """
        트리밍 명령 실행
        """
        try:
            # 여기에 실제 트리밍 적용 코드 구현
            # 예: media_manager.set_trim(self.file_id, self.new_start, self.new_end)
            self.logger.debug(f"파일 {self.file_id}에 트리밍 적용: {self.new_start}-{self.new_end}")
            return True
        except Exception as e:
            self.logger.error(f"트리밍 명령 실행 중 오류: {str(e)}")
            return False
    
    def undo(self) -> bool:
        """
        트리밍 명령 취소
        """
        try:
            # 여기에 실제 트리밍 취소 코드 구현
            # 예: media_manager.set_trim(self.file_id, self.old_start, self.old_end)
            self.logger.debug(f"파일 {self.file_id}에 트리밍 취소: {self.old_start}-{self.old_end}")
            return True
        except Exception as e:
            self.logger.error(f"트리밍 명령 취소 중 오류: {str(e)}")
            return False


class EncodingOptionsCommand(Command):
    """
    인코딩 옵션 변경 명령
    """
    
    def __init__(self, old_options: Dict[str, Any], new_options: Dict[str, Any]):
        """
        인코딩 옵션 변경 명령 초기화
        
        Args:
            old_options: 이전 인코딩 옵션
            new_options: 새 인코딩 옵션
        """
        super().__init__("인코딩 옵션 변경")
        self.old_options = old_options.copy()
        self.new_options = new_options.copy()
    
    def execute(self) -> bool:
        """
        인코딩 옵션 변경 명령 실행
        """
        try:
            # 여기에 실제 인코딩 옵션 적용 코드 구현
            # 예: encoding_manager.set_options(self.new_options)
            self.logger.debug(f"인코딩 옵션 적용: {self.new_options}")
            return True
        except Exception as e:
            self.logger.error(f"인코딩 옵션 변경 명령 실행 중 오류: {str(e)}")
            return False
    
    def undo(self) -> bool:
        """
        인코딩 옵션 변경 명령 취소
        """
        try:
            # 여기에 실제 인코딩 옵션 취소 코드 구현
            # 예: encoding_manager.set_options(self.old_options)
            self.logger.debug(f"인코딩 옵션 취소: {self.old_options}")
            return True
        except Exception as e:
            self.logger.error(f"인코딩 옵션 변경 명령 취소 중 오류: {str(e)}")
            return False


class SetInPointCommand(Command):
    """시작 프레임 마커 설정 명령"""
    
    def __init__(self, timeline_widget, old_in_point: int, new_in_point: int):
        """
        시작 프레임 마커 설정 명령 초기화
        
        Args:
            timeline_widget: 타임라인 위젯
            old_in_point: 이전 시작 프레임
            new_in_point: 새 시작 프레임
        """
        super().__init__(f"시작 프레임 설정: {old_in_point} → {new_in_point}")
        self.timeline_widget = timeline_widget
        self.old_in_point = old_in_point
        self.new_in_point = new_in_point
    
    def execute(self) -> bool:
        """시작 프레임 마커 설정 명령 실행"""
        try:
            self.timeline_widget.set_in_point(self.new_in_point)
            return True
        except Exception as e:
            self.logger.error(f"시작 프레임 설정 명령 실행 중 오류: {str(e)}")
            return False
    
    def undo(self) -> bool:
        """시작 프레임 마커 설정 명령 취소"""
        try:
            self.timeline_widget.set_in_point(self.old_in_point)
            return True
        except Exception as e:
            self.logger.error(f"시작 프레임 설정 명령 취소 중 오류: {str(e)}")
            return False


class SetOutPointCommand(Command):
    """종료 프레임 마커 설정 명령"""
    
    def __init__(self, timeline_widget, old_out_point: int, new_out_point: int):
        """
        종료 프레임 마커 설정 명령 초기화
        
        Args:
            timeline_widget: 타임라인 위젯
            old_out_point: 이전 종료 프레임
            new_out_point: 새 종료 프레임
        """
        super().__init__(f"종료 프레임 설정: {old_out_point} → {new_out_point}")
        self.timeline_widget = timeline_widget
        self.old_out_point = old_out_point
        self.new_out_point = new_out_point
    
    def execute(self) -> bool:
        """종료 프레임 마커 설정 명령 실행"""
        try:
            self.timeline_widget.set_out_point(self.new_out_point)
            return True
        except Exception as e:
            self.logger.error(f"종료 프레임 설정 명령 실행 중 오류: {str(e)}")
            return False
    
    def undo(self) -> bool:
        """종료 프레임 마커 설정 명령 취소"""
        try:
            self.timeline_widget.set_out_point(self.old_out_point)
            return True
        except Exception as e:
            self.logger.error(f"종료 프레임 설정 명령 취소 중 오류: {str(e)}")
            return False


class SeekFrameCommand(Command):
    """프레임 이동 명령"""
    
    def __init__(self, timeline_widget, current_frame: int, target_frame: int, video_thread=None):
        """
        프레임 이동 명령 초기화
        
        Args:
            timeline_widget: 타임라인 위젯
            current_frame: 현재 프레임
            target_frame: 이동할 프레임
            video_thread: 비디오 스레드 (선택 사항)
        """
        super().__init__(f"프레임 이동: {current_frame} → {target_frame}")
        self.timeline_widget = timeline_widget
        self.current_frame = current_frame
        self.target_frame = target_frame
        self.video_thread = video_thread
    
    def execute(self) -> bool:
        """프레임 이동 명령 실행"""
        try:
            # 타임라인 위젯 프레임 설정
            self.timeline_widget.set_current_frame(self.target_frame)
            
            # 비디오 스레드가 있으면 해당 프레임으로 이동
            if self.video_thread:
                self.video_thread.seek_to_frame(self.target_frame)
                
            return True
        except Exception as e:
            self.logger.error(f"프레임 이동 명령 실행 중 오류: {str(e)}")
            return False
    
    def undo(self) -> bool:
        """프레임 이동 명령 취소"""
        try:
            # 타임라인 위젯 프레임 설정
            self.timeline_widget.set_current_frame(self.current_frame)
            
            # 비디오 스레드가 있으면 해당 프레임으로 이동
            if self.video_thread:
                self.video_thread.seek_to_frame(self.current_frame)
                
            return True
        except Exception as e:
            self.logger.error(f"프레임 이동 명령 취소 중 오류: {str(e)}")
            return False


# 전역 명령 관리자 인스턴스
command_manager = CommandManager() 